# ARM Architecture Migration Guide

This document describes the changes made to migrate the MCP Local Server to support ARM architecture.

## Changes Made

### 1. Dockerfile Updates

The Dockerfile has been updated to support multi-platform builds:

```dockerfile
# Multi-platform build support for ARM64 and AMD64
FROM --platform=$BUILDPLATFORM ubuntu:24.04 AS builder
```

**Key Changes:**
- Added `--platform=$BUILDPLATFORM` to both builder and runtime stages
- Maintained existing ARM migration tools installation
- Ubuntu 24.04 base image already supports ARM64 natively

### 2. Python Package Compatibility

All Python packages have been verified for ARM compatibility:

| Package | ARM Compatible | Notes |
|---------|---------------|--------|
| torch | ✅ | Works on ARM from v1.8.0+, recommended v2.0.0+ |
| pytorch | ✅ | Works on ARM from v1.8.0+, recommended v2.0.0+ |
| usearch | ✅ | Vector search library, ARM compatible |
| pyyaml | ✅ | Platform independent |
| boto3 | ✅ | AWS SDK, ARM compatible |
| requests | ✅ | HTTP library, ARM compatible |
| mcp | ✅ | Model Context Protocol, ARM compatible |
| sentence-transformers | ✅ | Depends on PyTorch, ARM compatible |
| fastmcp | ✅ | Fast MCP implementation, ARM compatible |
| beautifulsoup4 | ✅ | HTML parser, platform independent |

### 3. Requirements Updates

- Updated `pytorch>=2.3.0` in mcp-remote/requirements.txt for better ARM performance
- All other packages maintained at latest compatible versions

## Building for ARM

### Method 1: Using Docker Buildx

Build for multiple platforms including ARM64:

```bash
# Run the provided build script
./build-multiplatform.sh
```

### Method 2: Manual Buildx Command

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t mcp-local:latest .
```

### Method 3: ARM64 Only

```bash
docker buildx build --platform linux/arm64 -t mcp-local:arm64 .
```

## Running on ARM

### Using Docker

```bash
# Run on ARM64
docker run --platform linux/arm64 -v /workspace:/workspace mcp-local:latest

# Run with docker-compose (ARM service)
docker-compose up mcp-local-arm
```

### Native ARM Environment

The container will automatically detect ARM architecture and run optimally without any special flags when running on native ARM hardware.

## Performance Optimizations

### PyTorch ARM Optimizations

PyTorch 2.0+ includes optimizations for ARM Neoverse processors:
- SMMLA and FMMLA instruction set support
- Optimized GEMM kernels for bfloat16
- Better memory bandwidth utilization

### ARM Migration Tools

The existing ARM migration tools installation provides:
- migrate-ease for code analysis
- skopeo for container inspection  
- Performance analysis capabilities

## Verification

To verify ARM compatibility:

```bash
# Check architecture inside container
docker run --platform linux/arm64 mcp-local:latest uname -m
# Should output: aarch64

# Check PyTorch ARM support
docker run --platform linux/arm64 mcp-local:latest python -c "import torch; print(f'PyTorch {torch.__version__} on {torch.__file__}')"
```

## Benefits of ARM Migration

1. **Cost Efficiency**: ARM instances typically offer better price/performance ratio
2. **Energy Efficiency**: Lower power consumption for same workloads
3. **Performance**: Optimized libraries provide excellent performance on modern ARM processors
4. **Compatibility**: Multi-platform support ensures workloads run on both architectures
5. **Future-Proofing**: ARM adoption is growing rapidly in cloud and edge computing

## Troubleshooting

### Common Issues

1. **Platform Mismatch**: Ensure you're using the correct platform flag
2. **Binary Compatibility**: Some packages may need ARM64-specific wheels
3. **Performance**: Use PyTorch 2.0+ for optimal ARM performance

### Getting Help

- Check ARM ecosystem compatibility: https://www.arm.com/developer-hub/ecosystem-dashboard/
- PyTorch ARM documentation: https://learn.arm.com/install-guides/pytorch
- ARM migration tools: https://github.com/arm/arm-linux-migration-tools