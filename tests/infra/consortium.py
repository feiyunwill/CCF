# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache 2.0 License.

import array
import os
import json
import time
from enum import Enum
import infra.ccf
import infra.proc
import infra.checker
import infra.node

from loguru import logger as LOG


class Consortium:
    def __init__(self, members, curve):
        self.members = members
        members = [f"member{m}" for m in members]
        for m in members:
            infra.proc.ccall(
                "./keygenerator.sh", f"{m}", curve.name, log_output=False
            ).check_returncode()
        self.status = infra.ccf.ServiceStatus.OPEN

    def get_members_certs(self):
        members_certs = [f"member{m}_cert.pem" for m in self.members]
        return members_certs

    def _member_client_rpc_as_json(self, member_id, remote_node, *args):
        result = infra.proc.ccall(
            "./memberclient",
            f"--cert=member{member_id}_cert.pem",
            f"--privk=member{member_id}_privk.pem",
            f"--rpc-address={remote_node.host}:{remote_node.rpc_port}",
            "--ca=networkcert.pem",
            *args,
        )
        j_result = json.loads(result.stdout)
        return j_result

    def propose(self, member_id, remote_node, script=None, params=None):
        with remote_node.member_client(format="json", member_id=member_id) as mc:
            r = mc.rpc("propose", {"parameter": params, "script": {"text": script}})
            return r.result, r.error

    def vote(
        self,
        member_id,
        remote_node,
        proposal_id,
        accept,
        force_unsigned=False,
        should_wait_for_global_commit=True,
    ):
        if os.getenv("HTTP"):
            script = """
            tables, changes = ...
            return true
            """
            with remote_node.member_client(format="json", member_id=member_id) as mc:
                res = mc.rpc(
                    "vote",
                    {"ballot": {"text": script}, "id": proposal_id},
                    signed=not force_unsigned,
                )
                j_result = res.to_dict()

        else:
            j_result = self._member_client_rpc_as_json(
                member_id,
                remote_node,
                "vote",
                f"--proposal-id={proposal_id}",
                "--accept" if accept else "--reject",
                "--force-unsigned" if force_unsigned else "",
            )

        if "error" in j_result:
            return (False, j_result["error"])

        # If the proposal was accepted, wait for it to be globally committed
        # This is particularly useful for the open network proposal to wait
        # until the global hook on the SERVICE table is triggered
        if j_result["result"] and should_wait_for_global_commit:
            with remote_node.node_client() as mc:
                infra.checker.wait_for_global_commit(
                    mc, j_result["commit"], j_result["term"], True
                )

        return (True, j_result["result"])

    def vote_using_majority(
        self, remote_node, proposal_id, should_wait_for_global_commit=True
    ):
        # There is no need to stop after n / 2 + 1 members have voted,
        # but this could prove to be useful in detecting errors
        # related to the voting mechanism
        majority_count = int(len(self.members) / 2 + 1)
        for i, member in enumerate(self.members):
            if i >= majority_count:
                break
            res = self.vote(
                member,
                remote_node,
                proposal_id,
                True,
                False,
                should_wait_for_global_commit,
            )
            assert res[0]
            if res[1]:
                break

        assert res
        return res[1]

    def withdraw(self, member_id, remote_node, proposal_id):
        with remote_node.member_client(member_id=member_id) as c:
            return c.do("withdraw", {"id": proposal_id})

    def ack(self, member_id, remote_node):
        # TODO: Produce signed ack here
        return self._member_client_rpc_as_json(member_id, remote_node, "ack")

    def get_proposals(self, member_id, remote_node):
        script = """
        tables = ...
        local proposals = {}
        tables["ccf.proposals"]:foreach( function(k, v)
            proposals[tostring(k)] = v;
        end )
        return proposals;
        """

        with remote_node.member_client(format="json", member_id=member_id) as c:
            rep = c.do("query", {"text": script})
            return rep.result

    def propose_retire_node(self, member_id, remote_node, node_id):
        script = """
        tables, node_id = ...
        return Calls:call("retire_node", node_id)
        """
        return self.propose(member_id, remote_node, script, node_id)

    def retire_node(self, remote_node, node_to_retire):
        member_id = 1
        result, error = self.propose_retire_node(
            member_id, remote_node, node_to_retire.node_id
        )
        self.vote_using_majority(remote_node, result["id"])

        with remote_node.member_client(format="json") as c:
            id = c.request(
                "read", {"table": "ccf.nodes", "key": node_to_retire.node_id}
            )
            assert c.response(id).result["status"] == infra.node.NodeStatus.RETIRED.name

    def propose_trust_node(self, member_id, remote_node, node_id):
        script = """
        tables, node_id = ...
        return Calls:call("trust_node", node_id)
        """
        return self.propose(member_id, remote_node, script, node_id)

    def trust_node(self, member_id, remote_node, node_id):
        if not self._check_node_exists(
            remote_node, node_id, infra.node.NodeStatus.PENDING
        ):
            raise ValueError(f"Node {node_id} does not exist in state PENDING")

        result, error = self.propose_trust_node(member_id, remote_node, node_id)
        self.vote_using_majority(remote_node, result["id"])

        if not self._check_node_exists(
            remote_node, node_id, infra.node.NodeStatus.TRUSTED
        ):
            raise ValueError(f"Node {node_id} does not exist in state TRUSTED")

    def propose_add_member(self, member_id, remote_node, new_member_cert):
        script = """
        tables, member_cert = ...
        return Calls:call("new_member", member_cert)
        """
        with open(new_member_cert) as cert:
            new_member_cert_pem = [ord(c) for c in cert.read()]
        return self.propose(member_id, remote_node, script, new_member_cert_pem)

    def open_network(self, member_id, remote_node, pbft_open=False):
        """
        Assuming a network in state OPENING, this functions creates a new
        proposal and make members vote to transition the network to state
        OPEN.
        """
        script = """
        tables = ...
        return Calls:call("open_network")
        """
        result, error = self.propose(member_id, remote_node, script)
        self.vote_using_majority(remote_node, result["id"], pbft_open)
        self.check_for_service(remote_node, infra.ccf.ServiceStatus.OPEN)

    def rekey_ledger(self, member_id, remote_node):
        script = """
        tables = ...
        return Calls:call("rekey_ledger")
        """
        result, error = self.propose(member_id, remote_node, script)
        # Wait for global commit since sealed secrets are disclosed only
        # when the rekey transaction is globally committed.
        self.vote_using_majority(
            remote_node, result["id"], should_wait_for_global_commit=True
        )

    def add_users(self, remote_node, users):
        for u in users:
            user_cert = []
            with open(f"user{u}_cert.pem") as cert:
                user_cert = [ord(c) for c in cert.read()]
            script = """
            tables, user_cert = ...
            return Calls:call("new_user", user_cert)
            """
            result, error = self.propose(1, remote_node, script, user_cert)
            self.vote_using_majority(remote_node, result["id"])

    def set_lua_app(self, member_id, remote_node, app_script):
        script = """
        tables, app = ...
        return Calls:call("set_lua_app", app)
        """
        with open(app_script) as app:
            new_lua_app = app.read()
        result, error = self.propose(member_id, remote_node, script, new_lua_app)
        self.vote_using_majority(remote_node, result["id"])

    def set_js_app(self, member_id, remote_node, app_script):
        script = """
        tables, app = ...
        return Calls:call("set_js_app", app)
        """
        with open(app_script) as app:
            new_js_app = app.read()
        result, error = self.propose(member_id, remote_node, script, new_js_app)
        self.vote_using_majority(remote_node, result["id"])

    def accept_recovery(self, member_id, remote_node, sealed_secrets):
        script = """
        tables, sealed_secrets = ...
        return Calls:call("accept_recovery", sealed_secrets)
        """
        result, error = self.propose(member_id, remote_node, script, sealed_secrets)
        self.vote_using_majority(remote_node, result["id"])

    def add_new_code(self, member_id, remote_node, new_code_id):
        script = """
        tables, code_digest = ...
        return Calls:call("new_code", code_digest)
        """
        code_digest = list(bytearray.fromhex(new_code_id))
        result, error = self.propose(member_id, remote_node, script, code_digest)
        self.vote_using_majority(remote_node, result["id"])

    def check_for_service(self, remote_node, status):
        """
        Check via the member frontend of the given node that the certificate
        associated with current CCF service signing key has been recorded in
        the KV store with the appropriate status.
        """
        with remote_node.member_client(format="json") as c:
            rep = c.do(
                "query",
                {
                    "text": """tables = ...
                    return tables["ccf.service"]:get(0)"""
                },
            )
            current_status = rep.result["status"]
            current_cert = array.array("B", rep.result["cert"]).tobytes()

            expected_cert = open("networkcert.pem", "rb").read()
            assert (
                current_cert == expected_cert
            ), "Current service certificate did not match with networkcert.pem"
            assert (
                current_status == status.name
            ), f"Service status {current_status} (expected {status.name})"

    def _check_node_exists(self, remote_node, node_id, node_status=None):
        with remote_node.member_client(format="json") as c:
            rep = c.do("read", {"table": "ccf.nodes", "key": node_id})

            if rep.error is not None or (
                node_status and rep.result["status"] != node_status.name
            ):
                return False

        return True

    def wait_for_node_to_exist_in_store(
        self, remote_node, node_id, timeout, node_status=None,
    ):
        exists = False
        for _ in range(timeout):
            if self._check_node_exists(remote_node, node_id, node_status):
                exists = True
                break
            time.sleep(1)
        if not exists:
            raise TimeoutError(
                f"Node {node_id} has not yet been recorded in the store"
                + getattr(node_status, f" with status {node_status.name}", "")
            )
