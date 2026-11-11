package dev.wysp.intellij

/**
 * The JSON Schema subset used by action parameters (same keywords as the Python adapter SDK):
 * type, enum, const, properties, required, additionalProperties, items, minimum, maximum,
 * minLength, maxLength, minItems, maxItems, pattern. Unknown keywords are ignored.
 */
object Schema {
    fun validate(value: Any?, schema: Map<String, Any?>, path: String = "$"): List<String> {
        val problems = mutableListOf<String>()
        val t = schema["type"]
        if (t != null) {
            val names = (t as? List<*>)?.map { it.toString() } ?: listOf(t.toString())
            if (names.none { typeOk(value, it) }) {
                return listOf("$path: expected ${names.joinToString("/")}, got ${typeName(value)}")
            }
        }
        if (schema.containsKey("const") && value != schema["const"]) problems += "$path: must equal ${schema["const"]}"
        val enum = schema["enum"] as? List<*>
        if (enum != null && value !in enum) problems += "$path: must be one of $enum"
        if (value is Number) {
            val d = value.toDouble()
            (schema["minimum"] as? Number)?.let { if (d < it.toDouble()) problems += "$path: must be >= $it" }
            (schema["maximum"] as? Number)?.let { if (d > it.toDouble()) problems += "$path: must be <= $it" }
        }
        if (value is String) {
            val n = value.codePointCount(0, value.length)
            (schema["minLength"] as? Number)?.let { if (n < it.toInt()) problems += "$path: shorter than $it" }
            (schema["maxLength"] as? Number)?.let { if (n > it.toInt()) problems += "$path: longer than $it" }
            (schema["pattern"] as? String)?.let { if (!Regex(it).containsMatchIn(value)) problems += "$path: does not match '$it'" }
        }
        if (value is List<*>) {
            (schema["minItems"] as? Number)?.let { if (value.size < it.toInt()) problems += "$path: fewer than $it items" }
            (schema["maxItems"] as? Number)?.let { if (value.size > it.toInt()) problems += "$path: more than $it items" }
            @Suppress("UNCHECKED_CAST")
            val items = schema["items"] as? Map<String, Any?>
            if (items != null) value.forEachIndexed { i, item -> problems += validate(item, items, "$path[$i]") }
        }
        if (value is Map<*, *>) {
            @Suppress("UNCHECKED_CAST")
            val props = schema["properties"] as? Map<String, Map<String, Any?>> ?: emptyMap()
            for (name in (schema["required"] as? List<*>).orEmpty()) {
                if (!value.containsKey(name)) problems += "$path: missing required '$name'"
            }
            for ((name, sub) in props) if (value.containsKey(name)) problems += validate(value[name], sub, "$path.$name")
            if (schema["additionalProperties"] == false) {
                for (name in value.keys) if (name !in props) problems += "$path: unexpected '$name'"
            }
        }
        return problems
    }

    private fun typeOk(v: Any?, name: String): Boolean = when (name) {
        "string" -> v is String
        "integer" -> v is Long || v is Int || (v is Double && v == Math.rint(v) && v.isFinite())
        "number" -> v is Number
        "boolean" -> v is Boolean
        "array" -> v is List<*>
        "object" -> v is Map<*, *>
        "null" -> v == null
        else -> true
    }

    private fun typeName(v: Any?): String = when (v) {
        null -> "null"
        is String -> "string"
        is Boolean -> "boolean"
        is Number -> "number"
        is List<*> -> "array"
        is Map<*, *> -> "object"
        else -> v::class.simpleName ?: "value"
    }
}
