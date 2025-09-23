#ifndef PARTICLE_SIMULATOR_H
#define PARTICLE_SIMULATOR_H

#include <cstddef>
#include <cstdint>

class ParticleSimulator {
public:
    void update_positions_simd(float* x, float* y, float* vx, float* vy, int n);
    int count_set_bits(uint64_t n);
    void matrix_transpose_cache_optimized(float* src, float* dst, int n);
    void custom_memcpy(void* dst, const void* src, size_t n);
    
    // Baseline implementations for comparison
    void update_positions_baseline(float* x, float* y, float* vx, float* vy, int n);
    void matrix_transpose_baseline(float* src, float* dst, int n);
};

#endif // PARTICLE_SIMULATOR_H