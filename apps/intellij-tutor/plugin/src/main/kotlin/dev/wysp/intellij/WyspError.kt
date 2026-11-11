package dev.wysp.intellij

/** Contract error codes (see .kiro/steering/adapter-contract.md). */
object ErrorCode {
    const val INVALID_PARAMS = -32602
    const val METHOD_NOT_FOUND = -32601
    const val NOT_SUPPORTED = -32010
    const val ACTION_NOT_FOUND = -32011
    const val TARGET_NOT_FOUND = -32012
    const val PRECONDITION_FAILED = -32013
    const val EXECUTION_FAILED = -32014
    const val UNDO_UNAVAILABLE = -32015
    const val TIMEOUT = -32016
    const val BUSY = -32017
}

/** An error reported to the Core as a JSON-RPC error. `data` never holds stack traces. */
class WyspError(val code: Int, message: String, val data: Map<String, Any?>? = null) : RuntimeException(message) {
    fun toJson(): Map<String, Any?> = buildMap {
        put("code", code)
        put("message", message ?: "error")
        if (data != null) put("data", data)
    }
}
