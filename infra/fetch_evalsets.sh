#!/usr/bin/env bash
# infra/fetch_evalsets.sh — Download evaluation corpora and verify checksums.
# Enforces privacy policies by rejecting forbidden datasets.
set -e

# List of forbidden datasets (case-insensitive checks)
FORBIDDEN_DATASETS=(
    "ms-celeb-1m"
    "ms-celeb"
    "ms1m"
    "vggface2"
    "vggface"
    "vgg"
    "megaface"
    "casia-webface"
    "casia"
    "ijb-a"
    "ijb-b"
    "ijb-c"
    "ijb"
)

# Function to check for forbidden dataset names in arguments
check_args() {
    for arg in "$@"; do
        local lower_arg
        lower_arg=$(echo "$arg" | tr '[:upper:]' '[:lower:]')
        for forbidden in "${FORBIDDEN_DATASETS[@]}"; do
            if [[ "$lower_arg" == *"$forbidden"* ]]; then
                echo "ERROR: Dataset '$arg' is prohibited due to privacy, ethical, or licensing violations." >&2
                exit 1
            fi
        done
    done
}

# Run the arguments check
check_args "$@"

FIXTURES_DIR="fixtures/faces"
mkdir -p "$FIXTURES_DIR"

# Define SFHQ_256 shards to download
# We use shards 1 to 4 to get ~5,700 synthetic face images, sufficient to pad the gallery to N=5000.
DECLARE_SHARDS=(
    "shard_1_of_86.zip:32225e2206aad9e35d6c8aa5d4bff3fbdc7b39d53177e9ce2145831e4cc69693"
    "shard_2_of_86.zip:a2e2f3b63a7beffc68c97196bba596984529a51bf65e215a2bb2076675ff5bae"
    "shard_3_of_86.zip:9be2f095d019f94288b9c3c4a080db0c4e6af073c38b731a42cf2a47d03f2b8b"
    "shard_4_of_86.zip:8dd86af654cd3981f33e0b49b61145bd9ba2bcc3d3672a4483edb3ab5d060d6e"
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

# Download and verify
for item in "${DECLARE_SHARDS[@]}"; do
    filename="${item%%:*}"
    expected_sha="${item##*:}"
    filepath="$FIXTURES_DIR/$filename"

    echo "Checking $filename..."
    if [ -f "$filepath" ] && check_sha256 "$filepath" "$expected_sha"; then
        echo "$filename already exists and is valid. Skipping download."
    else
        echo "Downloading $filename..."
        curl -L -o "$filepath" "https://huggingface.co/datasets/pravsels/SFHQ_256/resolve/main/$filename"
        echo "Verifying checksum for $filename..."
        check_sha256 "$filepath" "$expected_sha"
    fi

    # Extract to fixtures/faces/sfhq
    echo "Extracting $filename..."
    unzip -q -o "$filepath" -d "$FIXTURES_DIR/sfhq"
done

# Generate LICENSES.md
echo "Generating LICENSES.md..."
cat <<EOF > "$FIXTURES_DIR/LICENSES.md"
# Evaluation Corpora Licenses

This directory contains evaluation datasets. Under the project's strict privacy policy, no raw face images of real individuals are committed to version control.

## SFHQ (Synthetic Faces High Quality)
* **Dataset**: pravsels/SFHQ_256 (shards 1-4)
* **Source**: Hugging Face (https://huggingface.co/datasets/pravsels/SFHQ_256)
* **License**: MIT License (https://github.com/SelfishGene/SFHQ-T2I-dataset)
* **Description**: High-quality synthetic faces used for impostor-gallery padding and evaluation.
EOF

echo "Acquisition complete!"
