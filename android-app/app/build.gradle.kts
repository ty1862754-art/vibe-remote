plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.viberemote.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.viberemote.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "0.5.0"
    }

    val keystoreFile = file("viberemote-signing.p12")
    val ksPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
    val ksAlias = System.getenv("ANDROID_KEY_ALIAS")
    val ksKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")

    signingConfigs {
        if (keystoreFile.exists() && !ksPassword.isNullOrBlank() && !ksAlias.isNullOrBlank()) {
            create("viberemote") {
                storeFile = keystoreFile
                storeType = "PKCS12"
                storePassword = ksPassword
                keyAlias = ksAlias
                keyPassword = ksKeyPassword ?: ksPassword
            }
        }
    }

    buildTypes {
        debug {
            signingConfigs.findByName("viberemote")?.let {
                signingConfig = it
            }
        }
        release {
            signingConfigs.findByName("viberemote")?.let {
                signingConfig = it
            }
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)

    val composeBom = platform(libs.androidx.compose.bom)
    implementation(composeBom)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)

    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.zxing.android.embedded)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
