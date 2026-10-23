plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val connectionAssets = tasks.register<Copy>("copyConnectionService") {
 from("../../crier") { include("connection-service.json") }
 into(layout.buildDirectory.dir("generated/connectionAssets"))
}
android {
 sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/connectionAssets"))
 namespace = "com.sentinel.crier"
 compileSdk = 35
 defaultConfig { applicationId = "com.sentinel.crier"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "1.0" }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
 sourceSets.getByName("test").resources.srcDir("../../tests/fixtures")
}
tasks.named("preBuild") { dependsOn(connectionAssets) }
dependencies { testImplementation("junit:junit:4.13.2") }
dependencies { testImplementation("org.json:json:20240303") }
