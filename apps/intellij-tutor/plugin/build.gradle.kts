import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm") version "2.4.0"
    id("org.jetbrains.intellij.platform") // version comes from the settings plugin (settings.gradle.kts)
}

group = "dev.wysp"
version = "0.1.0"

kotlin {
    jvmToolchain(25) // IntelliJ Platform 2026.2 runs on Java 25 (the IDE's bundled JBR)
}

dependencies {
    intellijPlatform {
        // Build against the IDE installed on this machine: no 1 GB SDK download.
        local(providers.gradleProperty("intellijPath"))
        bundledPlugin("com.intellij.modules.jcef") // optional at runtime: the embedded Panel
        testBundledPlugin("com.intellij.java") // platform tests use real Java PSI; the plugin itself needs no Java support
        testFramework(TestFrameworkType.Platform)
    }
    testImplementation("junit:junit:4.13.2") // the IntelliJ test framework runs on JUnit 4
    testImplementation("org.opentest4j:opentest4j:1.3.0")
}

intellijPlatform {
    buildSearchableOptions = false
    instrumentCode = false // only for Java GUI forms and @NotNull bytecode checks; this plugin is Kotlin without forms
    pluginConfiguration {
        ideaVersion {
            sinceBuild = "262"
            untilBuild = provider { null }
        }
    }
}

tasks.test {
    useJUnit()
}

// `gradlew runIde -PopenProject=<dir>` opens a project in the sandbox IDE; the flags skip first-run dialogs
// (data sharing consent, settings import, tips, project trust) so end-to-end checks run unattended.
val openProject = providers.gradleProperty("openProject")
tasks.runIde {
    argumentProviders.add(CommandLineArgumentProvider { listOfNotNull(openProject.orNull) })
    jvmArgumentProviders.add(CommandLineArgumentProvider {
        listOf(
            "-Djb.consents.confirmation.enabled=false",
            "-Djb.privacy.policy.text=<!--999.999-->",
            "-Didea.initially.ask.config=never",
            "-Dide.show.tips.on.startup.default.value=false",
            "-Didea.trust.all.projects=true",
        )
    })
}
