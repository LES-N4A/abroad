#!/usr/bin/env bash
# Builds the Abroad Android app into a signed APK without Gradle.
#
# Needs a JDK (17+) and an Android SDK with "platforms;android-34" and
# "build-tools;35.0.0". Point the script at them with JAVA_HOME and ANDROID_SDK:
#
#   JAVA_HOME=/c/tools/jdk ANDROID_SDK=/c/tools/android-sdk ./android/build.sh
#
# The APK is written to the path given as the first argument.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/../abroad-mobile-1.0.0.apk}"
JAVA_HOME="${JAVA_HOME:?set JAVA_HOME to a JDK 17 or newer}"
ANDROID_SDK="${ANDROID_SDK:?set ANDROID_SDK to an Android SDK path}"

BT="$ANDROID_SDK/build-tools/${BUILD_TOOLS:-35.0.0}"
JAR="$ANDROID_SDK/platforms/${PLATFORM:-android-34}/android.jar"
KEYSTORE="$HERE/abroad-release.jks"
STORE_PASS="abroad-classroom"

for tool in "$BT/aapt2.exe" "$BT/d8.bat" "$BT/zipalign.exe" "$BT/apksigner.bat" "$JAR"; do
    [ -e "$tool" ] || { echo "missing: $tool" >&2; exit 1; }
done

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
export PATH="$(dirname "$JAVA_HOME")/bin:$JAVA_HOME/bin:$PATH"

# The Java tools are Windows executables and do not understand MSYS paths
# (/c/..., /tmp/...) inside argument files, so hand them mixed Windows paths.
if command -v cygpath >/dev/null 2>&1; then
    win() { cygpath -m "$1"; }
else
    win() { printf '%s' "$1"; }
fi
BUILD_WIN="$(win "$BUILD")"

echo "[1/6] resources"
"$BT/aapt2.exe" compile --dir "$HERE/res" -o "$BUILD/res.zip"
"$BT/aapt2.exe" link -o "$BUILD/base.apk" -I "$JAR" \
    --manifest "$HERE/AndroidManifest.xml" -R "$BUILD/res.zip" \
    --java "$BUILD/gen" --auto-add-overlay

echo "[2/6] java"
mkdir -p "$BUILD/classes"
javac -nowarn -source 11 -target 11 -encoding UTF-8 -classpath "$JAR" \
    -d "$BUILD/classes" \
    $(find "$HERE/java" "$BUILD/gen" -name '*.java')

echo "[3/6] dex"
find "$BUILD/classes" -name '*.class' | sed "s|^$BUILD|$BUILD_WIN|" > "$BUILD/classes.txt"
"$BT/d8.bat" --lib "$(win "$JAR")" --min-api 21 --output "$BUILD_WIN" \
    "@$(win "$BUILD/classes.txt")"

echo "[4/6] package"
cp "$BUILD/base.apk" "$BUILD/unsigned.apk"
( cd "$BUILD" && "$JAVA_HOME/bin/jar.exe" uf unsigned.apk classes.dex )

echo "[5/6] align"
"$BT/zipalign.exe" -f -p 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "[6/6] sign"
if [ ! -f "$KEYSTORE" ]; then
    keytool -genkeypair -keystore "$KEYSTORE" -alias abroad -keyalg RSA -keysize 2048 \
        -validity 10950 -storepass "$STORE_PASS" -keypass "$STORE_PASS" \
        -dname "CN=Abroad, OU=Mobile, O=Abroad, L=Tunis, C=TN"
fi
"$BT/apksigner.bat" sign --ks "$KEYSTORE" --ks-key-alias abroad \
    --ks-pass "pass:$STORE_PASS" --key-pass "pass:$STORE_PASS" \
    --v4-signing-enabled false \
    --out "$OUT" "$BUILD/aligned.apk"
"$BT/apksigner.bat" verify --print-certs "$OUT" | head -4
"$BT/aapt2.exe" dump badging "$OUT" | grep -E "^(package|application-label|launchable-activity)"
echo "APK: $OUT"
