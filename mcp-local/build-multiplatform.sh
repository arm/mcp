#!/bin/bash

# Multi-platform Docker build script for ARM and AMD64
# This script builds the MCP local server for both ARM64 and AMD64 architectures

set -e

echo "Building MCP Local Server for multiple platforms..."

# Check if buildx is available
if ! docker buildx version > /dev/null 2>&1; then
    echo "Error: Docker buildx is required for multi-platform builds"
    echo "Please install Docker Desktop or enable buildx"
    exit 1
fi

# Create a new builder instance if it doesn't exist
BUILDER_NAME="mcp-multiplatform"
if ! docker buildx inspect $BUILDER_NAME > /dev/null 2>&1; then
    echo "Creating new buildx builder: $BUILDER_NAME"
    docker buildx create --name $BUILDER_NAME --driver docker-container --bootstrap
fi

# Use the multi-platform builder
docker buildx use $BUILDER_NAME

# Build for multiple platforms
echo "Building for linux/amd64 and linux/arm64..."
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag mcp-local:latest \
    --tag mcp-local:multiplatform \
    --push \
    .

echo "Multi-platform build completed successfully!"
echo ""
echo "To run on ARM64:"
echo "  docker run --platform linux/arm64 -v /workspace:/workspace mcp-local:latest"
echo ""
echo "To run on AMD64:"
echo "  docker run --platform linux/amd64 -v /workspace:/workspace mcp-local:latest"