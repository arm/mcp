#include "simulator.h"
#include <iostream>
#include <vector>
#include <chrono>
#include <random>
#include <cstring>
#include <iomanip>

void initialize_arrays(float* arr, int n, float min_val = -1.0f, float max_val = 1.0f) {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dis(min_val, max_val);
    
    for (int i = 0; i < n; ++i) {
        arr[i] = dis(gen);
    }
}

void benchmark_particle_update() {
    const int n = 100000;
    const int iterations = 1000;
    
    // Allocate aligned memory for SIMD
    float* x = (float*)aligned_alloc(32, n * sizeof(float));
    float* y = (float*)aligned_alloc(32, n * sizeof(float));
    float* vx = (float*)aligned_alloc(32, n * sizeof(float));
    float* vy = (float*)aligned_alloc(32, n * sizeof(float));
    
    initialize_arrays(x, n, 0, 100);
    initialize_arrays(y, n, 0, 100);
    initialize_arrays(vx, n, -1, 1);
    initialize_arrays(vy, n, -1, 1);
    
    ParticleSimulator sim;
    
    // Benchmark baseline
    auto start = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        sim.update_positions_baseline(x, y, vx, vy, n);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto baseline_time = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
    
    // Reset positions
    initialize_arrays(x, n, 0, 100);
    initialize_arrays(y, n, 0, 100);
    
    // Benchmark SIMD version (will only work on x86)
    #ifdef __x86_64__
    start = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        sim.update_positions_simd(x, y, vx, vy, n);
    }
    end = std::chrono::high_resolution_clock::now();
    auto simd_time = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
    
    std::cout << "Particle Update Benchmark (" << n << " particles, " << iterations << " iterations):\n";
    std::cout << "  Baseline: " << baseline_time << " μs\n";
    std::cout << "  SIMD:     " << simd_time << " μs\n";
    std::cout << "  Speedup:  " << std::fixed << std::setprecision(2) 
              << (float)baseline_time / simd_time << "x\n\n";
    #else
    std::cout << "SIMD version not available on this architecture\n\n";
    #endif
    
    free(x);
    free(y);
    free(vx);
    free(vy);
}

void test_bit_counting() {
    ParticleSimulator sim;
    uint64_t test_values[] = {
        0x0, 0xFFFFFFFFFFFFFFFF, 0xAAAAAAAAAAAAAAAA, 
        0x123456789ABCDEF0, 0x0F0F0F0F0F0F0F0F
    };
    
    std::cout << "Bit Counting Tests:\n";
    for (auto val : test_values) {
        int count = sim.count_set_bits(val);
        std::cout << "  0x" << std::hex << val << " has " << std::dec << count << " bits set\n";
    }
    std::cout << "\n";
}

void benchmark_matrix_transpose() {
    const int n = 512;  // Matrix size
    const int iterations = 100;
    
    float* src = new float[n * n];
    float* dst = new float[n * n];
    
    initialize_arrays(src, n * n);
    
    ParticleSimulator sim;
    
    // Benchmark baseline
    auto start = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        sim.matrix_transpose_baseline(src, dst, n);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto baseline_time = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
    
    // Benchmark cache-optimized version
    start = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        sim.matrix_transpose_cache_optimized(src, dst, n);
    }
    end = std::chrono::high_resolution_clock::now();
    auto optimized_time = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
    
    std::cout << "Matrix Transpose Benchmark (" << n << "x" << n << ", " << iterations << " iterations):\n";
    std::cout << "  Baseline:        " << baseline_time << " μs\n";
    std::cout << "  Cache-optimized: " << optimized_time << " μs\n";
    std::cout << "  Speedup:         " << std::fixed << std::setprecision(2) 
              << (float)baseline_time / optimized_time << "x\n\n";
    
    delete[] src;
    delete[] dst;
}

int main() {
    std::cout << "=== Particle Simulator Benchmark ===\n\n";
    
    #ifdef __x86_64__
    std::cout << "Platform: x86-64\n\n";
    #elif defined(__aarch64__)
    std::cout << "Platform: ARM64/AArch64\n\n";
    #else
    std::cout << "Platform: Unknown\n\n";
    #endif
    
    benchmark_particle_update();
    test_bit_counting();
    benchmark_matrix_transpose();
    
    return 0;
}