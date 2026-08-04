#!/usr/bin/env bash
# infra/fetch_models.sh — Download and verify checksums of ONNX model files.
set -e

MODELS_DIR="models"
mkdir -p "$MODELS_DIR"

# Checksum file path
CHECKSUM_FILE="$MODELS_DIR/checksums.txt"

# Model list: filename:url
MODEL_LIST=(
    "det_10g.onnx:https://huggingface.co/lithiumice/insightface/resolve/main/models/buffalo_l/det_10g.onnx"
    "w600k_r50.onnx:https://huggingface.co/lithiumice/insightface/resolve/main/models/buffalo_l/w600k_r50.onnx"
    "2.7_80x80_MiniFASNetV2.onnx:https://raw.githubusercontent.com/QingHeYang/Silent-Face-Anti-Spoofing-onnx/main/onnx/2.7_80x80_MiniFASNetV2.onnx"
    "4_0_0_80x80_MiniFASNetV1SE.onnx:https://raw.githubusercontent.com/QingHeYang/Silent-Face-Anti-Spoofing-onnx/main/onnx/4_0_0_80x80_MiniFASNetV1SE.onnx"
)

check_sha256() {
    local file=$1
    local expected=$2
    local actual=""
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$file" | awk '{print $1}')
    else
        actual=$(shasum -a 256 "$file" | awk '{print $1}')
    fi
    if [ "$actual" != "$expected" ]; then
        echo "Checksum mismatch for $file! Expected $expected, got $actual" >&2
        return 1
    fi
    return 0
}

# Function to get expected checksum from CHECKSUM_FILE
get_expected_checksum() {
    local target_filename=$1
    local expected_sha=""
    if [ -f "$CHECKSUM_FILE" ]; then
        while read -r sha filename; do
            if [ "$filename" = "$target_filename" ]; then
                expected_sha="$sha"
                break
            fi
        done < "$CHECKSUM_FILE"
    fi
    echo "$expected_sha"
}

# Download and verify models
for item in "${MODEL_LIST[@]}"; do
    filename="${item%%:*}"
    url="${item#*:}"
    filepath="$MODELS_DIR/$filename"
    
    expected_sha=$(get_expected_checksum "$filename")

    if [ -z "$expected_sha" ]; then
        echo "ERROR: No checksum found in $CHECKSUM_FILE for $filename" >&2
        exit 1
    fi

    echo "Checking $filename..."
    if [ -f "$filepath" ] && check_sha256 "$filepath" "$expected_sha"; then
        echo "$filename already exists and is valid. Skipping."
    else
        echo "Downloading $filename..."
        curl -L -o "$filepath" "$url"
        echo "Verifying checksum for $filename..."
        check_sha256 "$filepath" "$expected_sha"
    fi
done

echo "All models successfully downloaded and verified!"
