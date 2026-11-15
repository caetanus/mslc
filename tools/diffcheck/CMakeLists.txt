# Opt-in (-DMSLC_DIFFCHECK=ON). Every test here exits 77 (SKIP) when the GPU side it
# needs is not on the machine, so enabling the option never makes a build red.
find_library(DIFFCHECK_VULKAN_LIB vulkan HINTS /opt/homebrew/lib /usr/local/lib)
find_path(DIFFCHECK_VULKAN_INCLUDE vulkan/vulkan.h HINTS /opt/homebrew/include /usr/local/include)

set(DIFFCHECK_SRC ${CMAKE_SOURCE_DIR}/tools/diffcheck)
set(DIFFCHECK_TESTS ${CMAKE_SOURCE_DIR}/tests)

add_test(NAME diffcheck/compare COMMAND ${PYTHON3} ${DIFFCHECK_TESTS}/diffcheck_compare_test.py)
add_test(NAME diffcheck/inputs COMMAND ${PYTHON3} ${DIFFCHECK_TESTS}/diffcheck_inputs_test.py)
add_test(NAME diffcheck/checks COMMAND ${PYTHON3} ${DIFFCHECK_TESTS}/diffcheck_checks_test.py)

if(DIFFCHECK_VULKAN_LIB AND DIFFCHECK_VULKAN_INCLUDE)
	add_executable(diffcheck-vkhost ${DIFFCHECK_SRC}/vkhost.c)
	target_include_directories(diffcheck-vkhost PRIVATE ${DIFFCHECK_VULKAN_INCLUDE})
	target_link_libraries(diffcheck-vkhost PRIVATE ${DIFFCHECK_VULKAN_LIB})
	add_test(NAME diffcheck/vkhost COMMAND ${PYTHON3} ${DIFFCHECK_TESTS}/diffcheck_vkhost_test.py
		$<TARGET_FILE:mslc-cli> $<TARGET_FILE:diffcheck-vkhost> ${DIFFCHECK_TESTS}/diffcheck/fma_kernel.metal)
	set_tests_properties(diffcheck/vkhost PROPERTIES SKIP_RETURN_CODE 77)
else()
	message(STATUS "diffcheck: no Vulkan loader or headers, the Vulkan host is not built")
endif()

if(APPLE)
	enable_language(OBJCXX)
	add_executable(diffcheck-metalhost ${DIFFCHECK_SRC}/metalhost.mm)
	target_compile_options(diffcheck-metalhost PRIVATE -fobjc-arc)
	target_link_libraries(diffcheck-metalhost PRIVATE "-framework Metal" "-framework Foundation")
	add_test(NAME diffcheck/metalhost COMMAND ${PYTHON3} ${DIFFCHECK_TESTS}/diffcheck_metalhost_test.py
		$<TARGET_FILE:diffcheck-metalhost> ${DIFFCHECK_TESTS}/diffcheck/fma_kernel.metal
		${DIFFCHECK_TESTS}/diffcheck/struct_kernel.metal)
	set_tests_properties(diffcheck/metalhost PROPERTIES SKIP_RETURN_CODE 77)
else()
	message(STATUS "diffcheck: not macOS, the Metal host is not built")
endif()
