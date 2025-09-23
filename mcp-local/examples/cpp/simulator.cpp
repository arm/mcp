#include "simulator.h"
#include <immintrin.h>  // Intel intrinsics - will fail on ARM
#include <omp.h>
#include <vector>
#include <cstring>

void ParticleSimulator::update_positions_simd(float* x, float* y, float* vx, float* vy, int n) {
    // Intel AVX2 optimized loop - NOT portable to ARM
    #pragma omp parallel for
    for (int i = 0; i < n; i += 8) {
        __m256 px = _mm256_load_ps(&x[i]);
        __m256 py = _mm256_load_ps(&y[i]);
        __m256 pvx = _mm256_load_ps(&vx[i]);
        __m256 pvy = _mm256_load_ps(&vy[i]);
        
        px = _mm256_add_ps(px, pvx);
        py = _mm256_add_ps(py, pvy);
        
        _mm256_store_ps(&x[i], px);
        _mm256_store_ps(&y[i], py);
    }
}

int ParticleSimulator::count_set_bits(uint64_t n) {
    // This builtin is actually portable, but let's add x86 assembly alternative
    #ifdef USE_X86_ASM
        int count;
        __asm__ __volatile__(
            "popcnt %1, %0"
            : "=r" (count)
            : "r" (n)
        );
        return count;
    #else
        return __builtin_popcountll(n);
    #endif
}

void ParticleSimulator::matrix_transpose_cache_optimized(float* src, float* dst, int n) {
    // Optimized for Intel cache line size (64 bytes)
    const int block = 64 / sizeof(float);  // 16 floats per cache line on x86
    
    #pragma omp parallel for collapse(2)
    for (int i = 0; i < n; i += block) {
        for (int j = 0; j < n; j += block) {
            // x86 prefetch instruction
            _mm_prefetch((char*)&src[i * n + j + block], _MM_HINT_T0);
            
            for (int ii = i; ii < i + block && ii < n; ++ii) {
                for (int jj = j; jj < j + block && jj < n; ++jj) {
                    dst[jj * n + ii] = src[ii * n + jj];
                }
            }
        }
    }
}

void ParticleSimulator::custom_memcpy(void* dst, const void* src, size_t n) {
    #ifdef __x86_64__
        // x86-64 specific inline assembly using REP MOVSB
        __asm__ __volatile__(
            "rep movsb"
            : "+D" (dst), "+S" (src), "+c" (n)
            :
            : "memory"
        );
    #else
        // Fallback for non-x86
        std::memcpy(dst, src, n);
    #endif
}

// Baseline implementations for comparison
void ParticleSimulator::update_positions_baseline(float* x, float* y, float* vx, float* vy, int n) {
    #pragma omp parallel for
    for (int i = 0; i < n; ++i) {
        x[i] += vx[i];
        y[i] += vy[i];
    }
}

void ParticleSimulator::matrix_transpose_baseline(float* src, float* dst, int n) {
    #pragma omp parallel for collapse(2)
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            dst[j * n + i] = src[i * n + j];
        }
    }
}