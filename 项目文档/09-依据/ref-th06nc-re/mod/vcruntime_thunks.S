	.text
	.globl t___AdjustPointer
t___AdjustPointer:
	jmp *rp___AdjustPointer(%rip)

	.data
	.globl rp___AdjustPointer
rp___AdjustPointer:
	.quad 0

	.text
	.globl t___BuildCatchObject
t___BuildCatchObject:
	jmp *rp___BuildCatchObject(%rip)

	.data
	.globl rp___BuildCatchObject
rp___BuildCatchObject:
	.quad 0

	.text
	.globl t___BuildCatchObjectHelper
t___BuildCatchObjectHelper:
	jmp *rp___BuildCatchObjectHelper(%rip)

	.data
	.globl rp___BuildCatchObjectHelper
rp___BuildCatchObjectHelper:
	.quad 0

	.text
	.globl t__CreateFrameInfo
t__CreateFrameInfo:
	jmp *rp__CreateFrameInfo(%rip)

	.data
	.globl rp__CreateFrameInfo
rp__CreateFrameInfo:
	.quad 0

	.text
	.globl t___C_specific_handler
t___C_specific_handler:
	jmp *rp___C_specific_handler(%rip)

	.data
	.globl rp___C_specific_handler
rp___C_specific_handler:
	.quad 0

	.text
	.globl t___C_specific_handler_noexcept
t___C_specific_handler_noexcept:
	jmp *rp___C_specific_handler_noexcept(%rip)

	.data
	.globl rp___C_specific_handler_noexcept
rp___C_specific_handler_noexcept:
	.quad 0

	.text
	.globl t___current_exception
t___current_exception:
	jmp *rp___current_exception(%rip)

	.data
	.globl rp___current_exception
rp___current_exception:
	.quad 0

	.text
	.globl t___current_exception_context
t___current_exception_context:
	jmp *rp___current_exception_context(%rip)

	.data
	.globl rp___current_exception_context
rp___current_exception_context:
	.quad 0

	.text
	.globl t___CxxDetectRethrow
t___CxxDetectRethrow:
	jmp *rp___CxxDetectRethrow(%rip)

	.data
	.globl rp___CxxDetectRethrow
rp___CxxDetectRethrow:
	.quad 0

	.text
	.globl t___CxxExceptionFilter
t___CxxExceptionFilter:
	jmp *rp___CxxExceptionFilter(%rip)

	.data
	.globl rp___CxxExceptionFilter
rp___CxxExceptionFilter:
	.quad 0

	.text
	.globl t___CxxFrameHandler
t___CxxFrameHandler:
	jmp *rp___CxxFrameHandler(%rip)

	.data
	.globl rp___CxxFrameHandler
rp___CxxFrameHandler:
	.quad 0

	.text
	.globl t___CxxFrameHandler2
t___CxxFrameHandler2:
	jmp *rp___CxxFrameHandler2(%rip)

	.data
	.globl rp___CxxFrameHandler2
rp___CxxFrameHandler2:
	.quad 0

	.text
	.globl t___CxxFrameHandler3
t___CxxFrameHandler3:
	jmp *rp___CxxFrameHandler3(%rip)

	.data
	.globl rp___CxxFrameHandler3
rp___CxxFrameHandler3:
	.quad 0

	.text
	.globl t___CxxQueryExceptionSize
t___CxxQueryExceptionSize:
	jmp *rp___CxxQueryExceptionSize(%rip)

	.data
	.globl rp___CxxQueryExceptionSize
rp___CxxQueryExceptionSize:
	.quad 0

	.text
	.globl t___CxxRegisterExceptionObject
t___CxxRegisterExceptionObject:
	jmp *rp___CxxRegisterExceptionObject(%rip)

	.data
	.globl rp___CxxRegisterExceptionObject
rp___CxxRegisterExceptionObject:
	.quad 0

	.text
	.globl t__CxxThrowException
t__CxxThrowException:
	jmp *rp__CxxThrowException(%rip)

	.data
	.globl rp__CxxThrowException
rp__CxxThrowException:
	.quad 0

	.text
	.globl t___CxxUnregisterExceptionObject
t___CxxUnregisterExceptionObject:
	jmp *rp___CxxUnregisterExceptionObject(%rip)

	.data
	.globl rp___CxxUnregisterExceptionObject
rp___CxxUnregisterExceptionObject:
	.quad 0

	.text
	.globl t___DestructExceptionObject
t___DestructExceptionObject:
	jmp *rp___DestructExceptionObject(%rip)

	.data
	.globl rp___DestructExceptionObject
rp___DestructExceptionObject:
	.quad 0

	.text
	.globl t__FindAndUnlinkFrame
t__FindAndUnlinkFrame:
	jmp *rp__FindAndUnlinkFrame(%rip)

	.data
	.globl rp__FindAndUnlinkFrame
rp__FindAndUnlinkFrame:
	.quad 0

	.text
	.globl t___FrameUnwindFilter
t___FrameUnwindFilter:
	jmp *rp___FrameUnwindFilter(%rip)

	.data
	.globl rp___FrameUnwindFilter
rp___FrameUnwindFilter:
	.quad 0

	.text
	.globl t___GetPlatformExceptionInfo
t___GetPlatformExceptionInfo:
	jmp *rp___GetPlatformExceptionInfo(%rip)

	.data
	.globl rp___GetPlatformExceptionInfo
rp___GetPlatformExceptionInfo:
	.quad 0

	.text
	.globl t__get_purecall_handler
t__get_purecall_handler:
	jmp *rp__get_purecall_handler(%rip)

	.data
	.globl rp__get_purecall_handler
rp__get_purecall_handler:
	.quad 0

	.text
	.globl t__get_unexpected
t__get_unexpected:
	jmp *rp__get_unexpected(%rip)

	.data
	.globl rp__get_unexpected
rp__get_unexpected:
	.quad 0

	.text
	.globl t___intrinsic_setjmp
t___intrinsic_setjmp:
	jmp *rp___intrinsic_setjmp(%rip)

	.data
	.globl rp___intrinsic_setjmp
rp___intrinsic_setjmp:
	.quad 0

	.text
	.globl t___intrinsic_setjmpex
t___intrinsic_setjmpex:
	jmp *rp___intrinsic_setjmpex(%rip)

	.data
	.globl rp___intrinsic_setjmpex
rp___intrinsic_setjmpex:
	.quad 0

	.text
	.globl t__IsExceptionObjectToBeDestroyed
t__IsExceptionObjectToBeDestroyed:
	jmp *rp__IsExceptionObjectToBeDestroyed(%rip)

	.data
	.globl rp__IsExceptionObjectToBeDestroyed
rp__IsExceptionObjectToBeDestroyed:
	.quad 0

	.text
	.globl t__is_exception_typeof
t__is_exception_typeof:
	jmp *rp__is_exception_typeof(%rip)

	.data
	.globl rp__is_exception_typeof
rp__is_exception_typeof:
	.quad 0

	.text
	.globl t__local_unwind
t__local_unwind:
	jmp *rp__local_unwind(%rip)

	.data
	.globl rp__local_unwind
rp__local_unwind:
	.quad 0

	.text
	.globl t_longjmp
t_longjmp:
	jmp *rp_longjmp(%rip)

	.data
	.globl rp_longjmp
rp_longjmp:
	.quad 0

	.text
	.globl t_memchr
t_memchr:
	jmp *rp_memchr(%rip)

	.data
	.globl rp_memchr
rp_memchr:
	.quad 0

	.text
	.globl t_memcmp
t_memcmp:
	jmp *rp_memcmp(%rip)

	.data
	.globl rp_memcmp
rp_memcmp:
	.quad 0

	.text
	.globl t_memcpy
t_memcpy:
	jmp *rp_memcpy(%rip)

	.data
	.globl rp_memcpy
rp_memcpy:
	.quad 0

	.text
	.globl t_memmove
t_memmove:
	jmp *rp_memmove(%rip)

	.data
	.globl rp_memmove
rp_memmove:
	.quad 0

	.text
	.globl t_memset
t_memset:
	jmp *rp_memset(%rip)

	.data
	.globl rp_memset
rp_memset:
	.quad 0

	.text
	.globl t___NLG_Dispatch2
t___NLG_Dispatch2:
	jmp *rp___NLG_Dispatch2(%rip)

	.data
	.globl rp___NLG_Dispatch2
rp___NLG_Dispatch2:
	.quad 0

	.text
	.globl t__NLG_Dispatch2
t__NLG_Dispatch2:
	jmp *rp__NLG_Dispatch2(%rip)

	.data
	.globl rp__NLG_Dispatch2
rp__NLG_Dispatch2:
	.quad 0

	.text
	.globl t__NLG_Return
t__NLG_Return:
	jmp *rp__NLG_Return(%rip)

	.data
	.globl rp__NLG_Return
rp__NLG_Return:
	.quad 0

	.text
	.globl t___NLG_Return2
t___NLG_Return2:
	jmp *rp___NLG_Return2(%rip)

	.data
	.globl rp___NLG_Return2
rp___NLG_Return2:
	.quad 0

	.text
	.globl t__NLG_Return2
t__NLG_Return2:
	jmp *rp__NLG_Return2(%rip)

	.data
	.globl rp__NLG_Return2
rp__NLG_Return2:
	.quad 0

	.text
	.globl t___processing_throw
t___processing_throw:
	jmp *rp___processing_throw(%rip)

	.data
	.globl rp___processing_throw
rp___processing_throw:
	.quad 0

	.text
	.globl t__purecall
t__purecall:
	jmp *rp__purecall(%rip)

	.data
	.globl rp__purecall
rp__purecall:
	.quad 0

	.text
	.globl t___report_gsfailure
t___report_gsfailure:
	jmp *rp___report_gsfailure(%rip)

	.data
	.globl rp___report_gsfailure
rp___report_gsfailure:
	.quad 0

	.text
	.globl t___RTCastToVoid
t___RTCastToVoid:
	jmp *rp___RTCastToVoid(%rip)

	.data
	.globl rp___RTCastToVoid
rp___RTCastToVoid:
	.quad 0

	.text
	.globl t___RTDynamicCast
t___RTDynamicCast:
	jmp *rp___RTDynamicCast(%rip)

	.data
	.globl rp___RTDynamicCast
rp___RTDynamicCast:
	.quad 0

	.text
	.globl t___RTtypeid
t___RTtypeid:
	jmp *rp___RTtypeid(%rip)

	.data
	.globl rp___RTtypeid
rp___RTtypeid:
	.quad 0

	.text
	.globl t__set_purecall_handler
t__set_purecall_handler:
	jmp *rp__set_purecall_handler(%rip)

	.data
	.globl rp__set_purecall_handler
rp__set_purecall_handler:
	.quad 0

	.text
	.globl t__set_se_translator
t__set_se_translator:
	jmp *rp__set_se_translator(%rip)

	.data
	.globl rp__set_se_translator
rp__set_se_translator:
	.quad 0

	.text
	.globl t_set_unexpected
t_set_unexpected:
	jmp *rp_set_unexpected(%rip)

	.data
	.globl rp_set_unexpected
rp_set_unexpected:
	.quad 0

	.text
	.globl t__SetWinRTOutOfMemoryExceptionCallback
t__SetWinRTOutOfMemoryExceptionCallback:
	jmp *rp__SetWinRTOutOfMemoryExceptionCallback(%rip)

	.data
	.globl rp__SetWinRTOutOfMemoryExceptionCallback
rp__SetWinRTOutOfMemoryExceptionCallback:
	.quad 0

	.text
	.globl t___std_exception_copy
t___std_exception_copy:
	jmp *rp___std_exception_copy(%rip)

	.data
	.globl rp___std_exception_copy
rp___std_exception_copy:
	.quad 0

	.text
	.globl t___std_exception_destroy
t___std_exception_destroy:
	jmp *rp___std_exception_destroy(%rip)

	.data
	.globl rp___std_exception_destroy
rp___std_exception_destroy:
	.quad 0

	.text
	.globl t___std_terminate
t___std_terminate:
	jmp *rp___std_terminate(%rip)

	.data
	.globl rp___std_terminate
rp___std_terminate:
	.quad 0

	.text
	.globl t___std_type_info_compare
t___std_type_info_compare:
	jmp *rp___std_type_info_compare(%rip)

	.data
	.globl rp___std_type_info_compare
rp___std_type_info_compare:
	.quad 0

	.text
	.globl t___std_type_info_destroy_list
t___std_type_info_destroy_list:
	jmp *rp___std_type_info_destroy_list(%rip)

	.data
	.globl rp___std_type_info_destroy_list
rp___std_type_info_destroy_list:
	.quad 0

	.text
	.globl t___std_type_info_hash
t___std_type_info_hash:
	jmp *rp___std_type_info_hash(%rip)

	.data
	.globl rp___std_type_info_hash
rp___std_type_info_hash:
	.quad 0

	.text
	.globl t___std_type_info_name
t___std_type_info_name:
	jmp *rp___std_type_info_name(%rip)

	.data
	.globl rp___std_type_info_name
rp___std_type_info_name:
	.quad 0

	.text
	.globl t_strchr
t_strchr:
	jmp *rp_strchr(%rip)

	.data
	.globl rp_strchr
rp_strchr:
	.quad 0

	.text
	.globl t_strrchr
t_strrchr:
	jmp *rp_strrchr(%rip)

	.data
	.globl rp_strrchr
rp_strrchr:
	.quad 0

	.text
	.globl t_strstr
t_strstr:
	jmp *rp_strstr(%rip)

	.data
	.globl rp_strstr
rp_strstr:
	.quad 0

	.text
	.globl t___telemetry_main_invoke_trigger
t___telemetry_main_invoke_trigger:
	jmp *rp___telemetry_main_invoke_trigger(%rip)

	.data
	.globl rp___telemetry_main_invoke_trigger
rp___telemetry_main_invoke_trigger:
	.quad 0

	.text
	.globl t___telemetry_main_return_trigger
t___telemetry_main_return_trigger:
	jmp *rp___telemetry_main_return_trigger(%rip)

	.data
	.globl rp___telemetry_main_return_trigger
rp___telemetry_main_return_trigger:
	.quad 0

	.text
	.globl t___TypeMatch
t___TypeMatch:
	jmp *rp___TypeMatch(%rip)

	.data
	.globl rp___TypeMatch
rp___TypeMatch:
	.quad 0

	.text
	.globl t___uncaught_exception
t___uncaught_exception:
	jmp *rp___uncaught_exception(%rip)

	.data
	.globl rp___uncaught_exception
rp___uncaught_exception:
	.quad 0

	.text
	.globl t___uncaught_exceptions
t___uncaught_exceptions:
	jmp *rp___uncaught_exceptions(%rip)

	.data
	.globl rp___uncaught_exceptions
rp___uncaught_exceptions:
	.quad 0

	.text
	.globl t___unDName
t___unDName:
	jmp *rp___unDName(%rip)

	.data
	.globl rp___unDName
rp___unDName:
	.quad 0

	.text
	.globl t___unDNameEx
t___unDNameEx:
	jmp *rp___unDNameEx(%rip)

	.data
	.globl rp___unDNameEx
rp___unDNameEx:
	.quad 0

	.text
	.globl t_unexpected
t_unexpected:
	jmp *rp_unexpected(%rip)

	.data
	.globl rp_unexpected
rp_unexpected:
	.quad 0

	.text
	.globl t___vcrt_GetModuleFileNameW
t___vcrt_GetModuleFileNameW:
	jmp *rp___vcrt_GetModuleFileNameW(%rip)

	.data
	.globl rp___vcrt_GetModuleFileNameW
rp___vcrt_GetModuleFileNameW:
	.quad 0

	.text
	.globl t___vcrt_GetModuleHandleW
t___vcrt_GetModuleHandleW:
	jmp *rp___vcrt_GetModuleHandleW(%rip)

	.data
	.globl rp___vcrt_GetModuleHandleW
rp___vcrt_GetModuleHandleW:
	.quad 0

	.text
	.globl t___vcrt_InitializeCriticalSectionEx
t___vcrt_InitializeCriticalSectionEx:
	jmp *rp___vcrt_InitializeCriticalSectionEx(%rip)

	.data
	.globl rp___vcrt_InitializeCriticalSectionEx
rp___vcrt_InitializeCriticalSectionEx:
	.quad 0

	.text
	.globl t___vcrt_LoadLibraryExW
t___vcrt_LoadLibraryExW:
	jmp *rp___vcrt_LoadLibraryExW(%rip)

	.data
	.globl rp___vcrt_LoadLibraryExW
rp___vcrt_LoadLibraryExW:
	.quad 0

	.text
	.globl t_wcschr
t_wcschr:
	jmp *rp_wcschr(%rip)

	.data
	.globl rp_wcschr
rp_wcschr:
	.quad 0

	.text
	.globl t_wcsrchr
t_wcsrchr:
	jmp *rp_wcsrchr(%rip)

	.data
	.globl rp_wcsrchr
rp_wcsrchr:
	.quad 0

	.text
	.globl t_wcsstr
t_wcsstr:
	jmp *rp_wcsstr(%rip)

	.data
	.globl rp_wcsstr
rp_wcsstr:
	.quad 0

