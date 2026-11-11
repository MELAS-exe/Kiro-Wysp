package dev.wysp.intellij

/**
 * What may leave the IDE. Code text goes to the Core (and from there to the LLM provider), so only
 * the selection and the code at the caret are sent, bounded, and never from a sensitive file.
 */
object Privacy {
    const val MAX_SELECTION = 1500
    const val MAX_CODE_AT_CARET = 3000
    const val MAX_SIGNATURE = 120
    const val MAX_MESSAGE = 200

    // Matched against the file name, case-insensitively.
    private val SENSITIVE = listOf(
        Regex("^\\.env(\\..*)?$"),
        Regex(".*\\.(pem|key|p12|pfx|keystore|jks|der|crt|cer|kdbx)$"),
        Regex("^id_(rsa|dsa|ecdsa|ed25519)(\\..*)?$"),
        Regex(".*credential.*"),
        Regex(".*secret.*"),
        Regex("^\\.(netrc|pgpass|npmrc|pypirc)$"),
    )

    fun isSensitive(fileName: String): Boolean {
        val name = fileName.substringAfterLast('/').substringAfterLast('\\').lowercase()
        return SENSITIVE.any { it.matches(name) }
    }

    /** True when any segment of the path is sensitive (a file inside `secrets/` counts too). */
    fun isSensitivePath(path: String): Boolean = path.split('/', '\\').any { it.isNotEmpty() && isSensitive(it) }

    /** Cut a text to `max` characters, on a line boundary when one is close. */
    fun bound(text: String, max: Int): String {
        if (text.length <= max) return text
        var cut = text.lastIndexOf('\n', max)
        if (cut < max / 2) cut = max
        if (cut > 0 && Character.isHighSurrogate(text[cut - 1])) cut--
        return text.substring(0, cut) + "\n…"
    }

    fun oneLine(text: String, max: Int): String {
        val flat = text.replace(Regex("\\s+"), " ").trim()
        if (flat.length <= max) return flat
        var cut = max - 1
        if (cut > 0 && Character.isHighSurrogate(flat[cut - 1])) cut--
        return flat.substring(0, cut) + "…"
    }
}
