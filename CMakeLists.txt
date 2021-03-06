# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache 2.0 License.
cmake_minimum_required(VERSION 3.11)

set(CCF_DIR ${CMAKE_CURRENT_SOURCE_DIR})
include(${CCF_DIR}/cmake/preproject.cmake)

project(ccf
  VERSION 0.6
  LANGUAGES C CXX)

set(TESTS_SUFFIX $ENV{TESTS_SUFFIX})
message(STATUS "Setting TESTS_SUFFIX on performance tests to '${TESTS_SUFFIX}'")
set(ENV{BETTER_EXCEPTIONS} 1)

# Set the default install prefix for CCF. Users may override this value
# with the cmake command. For example:
#
#     $ cmake -DCMAKE_INSTALL_PREFIX=/opt/myplace ..
#
if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
  set(CMAKE_INSTALL_PREFIX
    "/opt/ccf/ccf-${PROJECT_VERSION}" CACHE PATH "Default install prefix" FORCE)
endif()

message(STATUS "CMAKE_INSTALL_PREFIX is '${CMAKE_INSTALL_PREFIX}'")

include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/common.cmake)

option(BUILD_TESTS "Build tests" ON)
option(BUILD_SMALLBANK "Build SmallBank sample app and clients" ON)

# TODO: remove once FTCP support is disabled
# MemberClient executable
add_executable(memberclient src/clients/memberclient.cpp)
use_client_mbedtls(memberclient)
target_link_libraries(memberclient PRIVATE
  ${CMAKE_THREAD_LIBS_INIT}
  ccfcrypto.host
  secp256k1.host
  http_parser.host
)

add_dependencies(memberclient flatbuffers)

# TODO: remove once FTCP support is disabled
# Logging Client executable
add_executable(logging_client src/clients/logging_client.cpp)
use_client_mbedtls(logging_client)
target_link_libraries(logging_client PRIVATE
  ${CMAKE_THREAD_LIBS_INIT}
  http_parser.host
)

add_enclave_lib(loggingenc
  SRCS
    src/apps/logging/logging.cpp
    src/apps/logging/stub_for_code_signing.cpp
)
sign_app_library(loggingenc
  ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/logging/oe_sign.conf
  ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/sample_key.pem
)

# Create patched alternative of library, to test code version changes
function(create_patched_enclave_lib name app_oe_conf_path enclave_sign_key_path)
  if(TARGET ${name})
    set(patched_name ${name}.patched)
    set(patched_lib_name lib${patched_name}.so)
    add_custom_command(
        OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/${patched_lib_name}
        COMMAND cp ${CMAKE_CURRENT_BINARY_DIR}/lib${name}.so ${CMAKE_CURRENT_BINARY_DIR}/${patched_lib_name}
        COMMAND PYTHONPATH=${CCF_DIR}/tests:$ENV{PYTHONPATH} python3 patch_binary.py -p ${CMAKE_CURRENT_BINARY_DIR}/${patched_lib_name}
        WORKING_DIRECTORY ${CCF_DIR}/tests
        DEPENDS ${name}
    )

    add_custom_target(${patched_name} ALL
      DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/${patched_lib_name}
    )
    sign_app_library(${patched_name} ${app_oe_conf_path} ${enclave_sign_key_path})
  endif()
endfunction()

create_patched_enclave_lib(loggingenc
  ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/logging/oe_sign.conf
  ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/sample_key.pem
)

set(OE_SIGN_PATH ${OE_BINDIR}/oesign)

if(BUILD_TESTS)
  enable_testing()

  # Unit tests
  add_unit_test(map_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/map_test.cpp)

  add_unit_test(json_schema
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/json_schema.cpp)

  add_unit_test(logger_json_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/logger_json_test.cpp)

  add_unit_test(kv_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/kv/test/kv_test.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/kv/test/kv_contention.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/kv/test/kv_serialisation.cpp)
  use_client_mbedtls(kv_test)
  target_link_libraries(kv_test PRIVATE
    ${CMAKE_THREAD_LIBS_INIT}
    secp256k1.host)

  add_unit_test(ds_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/ringbuffer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/messaging.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/oversized.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/serializer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ds/test/hash.cpp)
  target_link_libraries(ds_test PRIVATE
    ${CMAKE_THREAD_LIBS_INIT})

  add_unit_test(ledger_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/host/test/ledger.cpp)

  if (NOT PBFT)
    add_unit_test(raft_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/consensus/raft/test/main.cpp)
    target_link_libraries(raft_test PRIVATE
      ${CRYPTO_LIBRARY})

    add_unit_test(raft_enclave_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/consensus/raft/test/enclave.cpp)
    target_include_directories(raft_enclave_test PRIVATE
      ${CCFCRYPTO_INC})
    target_link_libraries(raft_enclave_test PRIVATE
      ${CRYPTO_LIBRARY}
      secp256k1.host)
  endif()

  add_unit_test(crypto_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/crypto/test/crypto.cpp)
  target_include_directories(crypto_test PRIVATE
    ${CCFCRYPTO_INC})
  target_link_libraries(crypto_test PRIVATE
    ${CRYPTO_LIBRARY})

   add_unit_test(history_test
     ${CMAKE_CURRENT_SOURCE_DIR}/src/node/test/history.cpp)
   target_include_directories(history_test PRIVATE
     ${EVERCRYPT_INC})
   target_link_libraries(history_test PRIVATE
     ${CRYPTO_LIBRARY}
     evercrypt.host
     secp256k1.host)

  add_unit_test(encryptor_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/node/test/encryptor.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/crypto/symmkey.cpp)
  use_client_mbedtls(encryptor_test)
  target_link_libraries(encryptor_test PRIVATE
    secp256k1.host)

  add_unit_test(msgpack_serialization_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/node/test/msgpack_serialization.cpp)

  add_unit_test(tls_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/tls/test/main.cpp)
  target_link_libraries(tls_test PRIVATE
    ${CMAKE_THREAD_LIBS_INIT}
    secp256k1.host)

  add_unit_test(keyexchange_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/tls/test/keyexchange.cpp)
  use_client_mbedtls(keyexchange_test)
  target_link_libraries(keyexchange_test PRIVATE
    secp256k1.host)

  add_unit_test(channels_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/node/test/channels.cpp)
  use_client_mbedtls(channels_test)
  target_link_libraries(channels_test PRIVATE secp256k1.host)

  add_unit_test(http_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/enclave/test/http.cpp)
  target_link_libraries(http_test PRIVATE http_parser.host)

  add_unit_test(frontend_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/node/rpc/test/frontend_test.cpp)
    target_link_libraries(frontend_test PRIVATE
      ${CMAKE_THREAD_LIBS_INIT}
      evercrypt.host
      lua.host
      secp256k1.host
    )

  if(NOT PBFT)
    add_unit_test(membervoting_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/node/rpc/test/membervoting_test.cpp)
    target_link_libraries(membervoting_test PRIVATE
      ${CMAKE_THREAD_LIBS_INIT}
      evercrypt.host
      lua.host
      secp256k1.host)

    add_unit_test(nodefrontend_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/node/rpc/test/nodefrontend_test.cpp)
    target_link_libraries(nodefrontend_test PRIVATE
      ${CMAKE_THREAD_LIBS_INIT}
      evercrypt.host
      lua.host
      secp256k1.host)

    if(NOT ENV{RUNTIME_CONFIG_DIR})
      set_tests_properties(membervoting_test PROPERTIES ENVIRONMENT RUNTIME_CONFIG_DIR=${CMAKE_SOURCE_DIR}/src/runtime_config)
    endif()

    add_unit_test(luageneric_test
      ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/luageneric/test/luageneric_test.cpp
      ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/luageneric/luageneric.cpp)
    target_include_directories(luageneric_test PRIVATE
      ${LUA_DIR})
    target_link_libraries(luageneric_test PRIVATE
      lua.host
      secp256k1.host)
  endif()

  add_unit_test(lua_test
    ${CMAKE_CURRENT_SOURCE_DIR}/src/luainterp/test/lua_test.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/luainterp/test/luakv.cpp)
  target_include_directories(lua_test PRIVATE
    ${LUA_DIR})
  target_link_libraries(lua_test PRIVATE
    lua.host)

  ## Picobench benchmarks
  add_picobench(map_bench
    SRCS src/ds/test/map_bench.cpp
  )
  add_picobench(logger_bench
    SRCS src/ds/test/logger_bench.cpp
  )
  add_picobench(json_bench
    SRCS src/ds/test/json_bench.cpp
  )
  add_picobench(ringbuffer_bench
    SRCS src/ds/test/ringbuffer_bench.cpp
  )
  add_picobench(tls_bench
    SRCS src/tls/test/bench.cpp
    LINK_LIBS secp256k1.host
  )
  add_picobench(merkle_bench
    SRCS src/node/test/merkle_bench.cpp
    LINK_LIBS ccfcrypto.host evercrypt.host secp256k1.host
    INCLUDE_DIRS ${EVERCRYPT_INC}
  )
  add_picobench(history_bench
    SRCS src/node/test/history_bench.cpp
    LINK_LIBS ccfcrypto.host evercrypt.host secp256k1.host
    INCLUDE_DIRS ${EVERCRYPT_INC}
  )
  add_picobench(kv_bench
    SRCS src/kv/test/kv_bench.cpp src/crypto/symmkey.cpp
  )

  # Merkle Tree memory test
  add_executable(merkle_mem src/node/test/merkle_mem.cpp)
  target_link_libraries(merkle_mem PRIVATE
    ccfcrypto.host
    evercrypt.host
    secp256k1.host
    ${CMAKE_THREAD_LIBS_INIT})
  use_client_mbedtls(merkle_mem)
  target_include_directories(merkle_mem PRIVATE
    ${EVERCRYPT_INC}
    src)
  add_dependencies(merkle_mem flatbuffers)

  if (NOT PBFT)
    # Raft driver and scenario test
    add_executable(raft_driver
      ${CMAKE_CURRENT_SOURCE_DIR}/src/consensus/raft/test/driver.cpp)
    use_client_mbedtls(raft_driver)
    target_include_directories(raft_driver PRIVATE
      src/raft)
    add_dependencies(raft_driver flatbuffers)
    add_test(
      NAME raft_scenario_test
      COMMAND
        ${PYTHON} ${CMAKE_SOURCE_DIR}/tests/raft_scenarios_runner.py ./raft_driver
          ${CMAKE_SOURCE_DIR}/tests/raft_scenarios ${CMAKE_SOURCE_DIR})
    set_property(TEST raft_scenario_test PROPERTY LABELS raft_scenario)

    ## Storing signed votes test
    add_e2e_test(
      NAME voting_history_test
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/votinghistory.py)


    # TODO: Sends an ACK via C++ memberclient, which must be signed.	    # Member client end to end tests
    # ACK should be sent from Python, AND HTTP memberclient should sign
      if (NOT HTTP)
      # Member client end to end tests
      add_e2e_test(
        NAME member_client_test
        PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/memberclient.py
      )
    endif()

    ## Logging client end to end test
    add_e2e_test(
      NAME logging_client_test
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/loggingclient.py
    )

    ## Lua sample app (tx regulator) end to end test
    add_e2e_test(
      NAME lua_txregulator_test
      PYTHON_SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/samples/apps/txregulator/tests/txregulatorclient.py
      ADDITIONAL_ARGS
        --app-script ${CMAKE_CURRENT_SOURCE_DIR}/samples/apps/txregulator/app/txregulator.lua
        --datafile ${CMAKE_CURRENT_SOURCE_DIR}/samples/apps/txregulator/dataset/sample_data.csv)

    ## Receipts end to end test
    add_e2e_test(
      NAME receipts_test
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/receipts.py
    )

    if(QUOTES_ENABLED)
      add_e2e_test(
        NAME governance_tests
        PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/governance.py
        ADDITIONAL_ARGS
          --oesign ${OE_SIGN_PATH}
      )
    endif()

    add_e2e_test(
      NAME recovery_tests
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/recovery.py
      ADDITIONAL_ARGS
        ${RECOVERY_ARGS}
    )

    add_e2e_test(
      NAME test_suite
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_suite.py
      IS_SUITE TRUE
      ADDITIONAL_ARGS
      --test-duration 150
      --enforce-reqs
    )

    add_e2e_test(
      NAME lua_end_to_end_batched
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_batched.py
      ADDITIONAL_ARGS
        --app-script ${CMAKE_SOURCE_DIR}/src/apps/batched/batched.lua)

    add_e2e_test(
      NAME end_to_end_logging
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_logging.py
      CURL_CLIENT TRUE
    )

    add_e2e_test(
      NAME js_end_to_end_logging
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_logging.py
      ADDITIONAL_ARGS
        --js-app-script ${CMAKE_SOURCE_DIR}/src/apps/logging/loggingjs.lua
    )

    add_e2e_test(
      NAME lua_end_to_end_logging
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_logging.py
      ADDITIONAL_ARGS
        --app-script ${CMAKE_SOURCE_DIR}/src/apps/logging/logging.lua
    )

    add_e2e_test(
      NAME end_to_end_scenario
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/e2e_scenarios.py
      ADDITIONAL_ARGS
        --scenario ${CMAKE_SOURCE_DIR}/tests/simple_logging_scenario.json
    )

    if (NOT SAN)
      add_e2e_test(
        NAME connections
        PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/connections.py
      )
    endif()

    add_e2e_test(
      NAME schema_tests
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/schema.py
      ADDITIONAL_ARGS
      -p libloggingenc
      --schema-dir ${CMAKE_SOURCE_DIR}/sphinx/source/schemas
    )

    if(QUOTES_ENABLED)
      add_e2e_test(
        NAME reconfiguration_test
        PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/reconfiguration.py
      )

      add_e2e_test(
        NAME code_update_test
        PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/code_update.py
        ADDITIONAL_ARGS
          --oesign ${OE_SIGN_PATH}
          --oeconfpath ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/logging/oe_sign.conf
          --oesignkeypath ${CMAKE_CURRENT_SOURCE_DIR}/src/apps/sample_key.pem
          # TODO: This test spins up many nodes that go through the join protocol
          # Since oe_verify_report can take quite a long time to execute (~2s)
          # and trigger Raft elections, the election timeout should stay high
          # until https://github.com/microsoft/CCF/issues/480 is fixed
          --election-timeout 10000
      )
    endif()

  else()
    message(STATUS "Using PBFT as consensus")
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/pbft.cmake)
  endif()

  if (BUILD_SMALLBANK)
    include(${CMAKE_CURRENT_SOURCE_DIR}/samples/apps/smallbank/smallbank.cmake)
  endif()

  # TODO: Fix signed HTTP RPCs with PBFT
  if (NOT (HTTP AND PBFT))
    add_e2e_test(
      NAME election_tests
      PYTHON_SCRIPT ${CMAKE_SOURCE_DIR}/tests/election.py
      ADDITIONAL_ARGS
        --election-timeout 2000
    )
  endif()

  if (NOT PBFT)
    # Logging scenario perf test
    add_perf_test(
      NAME logging_scenario_perf_test
      PYTHON_SCRIPT ${CMAKE_CURRENT_LIST_DIR}/tests/perfclient.py
      CLIENT_BIN ./scenario_perf_client
      LABEL log_scenario
      ADDITIONAL_ARGS
        --package libloggingenc
        --scenario-file ${CMAKE_CURRENT_LIST_DIR}/tests/perf_logging_scenario_100txs.json
        --max-writes-ahead 1000
        --repetitions 1000
    )
  endif()

  if (EXTENSIVE_TESTS)
    set_tests_properties(recovery_tests PROPERTIES TIMEOUT 2000)
  endif()
endif()
