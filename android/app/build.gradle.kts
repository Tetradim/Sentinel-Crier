import groovy.json.JsonSlurper

plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val releaseMetadata = JsonSlurper().parse(rootProject.file("../release.json")) as Map<*, *>
val releaseDefaults = mapOf("releaseVersionName" to releaseMetadata["version"].toString(),
 "releaseVersionCode" to releaseMetadata["android_version_code"].toString(),
 "previousReleaseVersionCode" to releaseMetadata["previous_android_version_code"].toString())
fun releaseInput(property: String, environment: String): String =
 providers.environmentVariable(environment).orElse(providers.gradleProperty(property)).orElse(releaseDefaults.getValue(property)).get()
val releaseCodeText = releaseInput("releaseVersionCode", "ANDROID_VERSION_CODE")
val previousCodeText = releaseInput("previousReleaseVersionCode", "ANDROID_PREVIOUS_VERSION_CODE")
val releaseCode = releaseCodeText.toIntOrNull()
val previousCode = previousCodeText.toIntOrNull()
require(releaseCode != null && releaseCode in 1..2100000000) { "Release versionCode must be an integer from 1 to 2100000000" }
require(previousCode != null && previousCode >= releaseDefaults.getValue("previousReleaseVersionCode").toInt() && requireNotNull(releaseCode) > previousCode) { "Release versionCode must exceed previousReleaseVersionCode (the highest distributed code); the recorded baseline cannot be lowered" }
val releaseName = releaseInput("releaseVersionName", "ANDROID_VERSION_NAME")
require(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)").matches(releaseName)) { "Release versionName must be stable MAJOR.MINOR.PATCH" }
val signingVariables = listOf("ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD")
val signingValues = signingVariables.associateWith { providers.environmentVariable(it).orNull }
val signingReady = signingValues.values.all { !it.isNullOrBlank() }
if (signingReady) require(file(signingValues.getValue("ANDROID_KEYSTORE_PATH")!!).isFile) { "Release keystore path must be an existing file" }
val connectionAssets = tasks.register<Copy>("copyConnectionService") {
 from("../../crier") { include("connection-service.json") }
 into(layout.buildDirectory.dir("generated/connectionAssets"))
}
android {
 sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/connectionAssets"))
 namespace = "com.sentinel.crier"
 compileSdk = 35
 defaultConfig { applicationId = "com.sentinel.crier"; minSdk = 26; targetSdk = 35; versionCode = requireNotNull(releaseCode); versionName = releaseName }
 signingConfigs {
  if (signingReady) create("release") {
   storeFile = file(signingValues.getValue("ANDROID_KEYSTORE_PATH")!!)
   storePassword = signingValues.getValue("ANDROID_KEYSTORE_PASSWORD")
   keyAlias = signingValues.getValue("ANDROID_KEY_ALIAS")
   keyPassword = signingValues.getValue("ANDROID_KEY_PASSWORD")
  }
 }
 buildTypes.getByName("release") {
  if (signingReady) signingConfig = signingConfigs.getByName("release")
 }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
 sourceSets.getByName("test").resources.srcDir("../../tests/fixtures")
}
tasks.named("preBuild") { dependsOn(connectionAssets) }
gradle.taskGraph.whenReady {
 val packagesRelease = allTasks.any { it.project == project && it.name in setOf("assembleRelease", "bundleRelease", "packageRelease", "signReleaseBundle", "validateSigningRelease") }
 require(!packagesRelease || signingReady) { "Release packaging requires all ANDROID_KEYSTORE_PATH, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, ANDROID_KEY_PASSWORD values; there is no debug signing fallback. Unsigned validation uses compileReleaseKotlin and processReleaseResources only." }
}
dependencies { testImplementation("junit:junit:4.13.2") }
dependencies { testImplementation("org.json:json:20240303") }
