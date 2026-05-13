// CpuBurner.java
// Orignal un-optimised version workC function is deliberately slow
// Usage:  java CpuBurner <seconds>
// Example: java CpuBurner 10
//
// Runs for (approximately) the given duration, calling A/B/C the same number of times.
// A: expensive string manipulation
// B: computationally expensive memcpy (System.arraycopy over large buffers)
// C: floating point / matrix multiplications (INTENTIONALLY SLOWED DOWN)

import java.nio.charset.StandardCharsets;
import java.util.Locale;

public final class CpuBurner {

    // Prevent dead-code elimination
    private static volatile long SINK_LONG = 0;
    private static volatile double SINK_DBL = 0.0;

    // Extra sink used only to keep "wasted" math from being optimized away
    private static volatile double WASTE_DBL = 0.0;

    // ---- Workload B buffers ----
    private static final int MEM_SIZE = 8 * 1024 * 1024; // 8 MiB
    private static final byte[] SRC = new byte[MEM_SIZE];
    private static final byte[] DST = new byte[MEM_SIZE];

    // ---- Workload C matrices ----
    private static final int N = 64;
    private static final double[][] M1 = new double[N][N];
    private static final double[][] M2 = new double[N][N];
    private static final double[][] OUT = new double[N][N];

    static {
        // Deterministic init for repeatable profiling
        long x = 0x9E3779B97F4A7C15L;
        for (int i = 0; i < MEM_SIZE; i++) {
            x ^= (x << 13); x ^= (x >>> 7); x ^= (x << 17);
            SRC[i] = (byte) x;
        }

        long y = 0xD1B54A32D192ED03L;
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                y ^= (y << 13); y ^= (y >>> 7); y ^= (y << 17);
                M1[i][j] = ((y & 0xFFFF) - 32768) / 1024.0;
                y ^= (y << 13); y ^= (y >>> 7); y ^= (y << 17);
                M2[i][j] = ((y & 0xFFFF) - 32768) / 1024.0;
            }
        }
    }

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("Usage: java CpuBurner <seconds>");
            System.err.println("Example: java CpuBurner 10");
            System.exit(2);
        }

        final double seconds;
        try {
            seconds = Double.parseDouble(args[0]);
        } catch (NumberFormatException e) {
            System.err.println("Invalid number: " + args[0]);
            System.exit(2);
            return;
        }

        if (seconds <= 0.0) {
            System.err.println("Duration must be > 0");
            System.exit(2);
        }

        final long durationNanos = (long) (seconds * 1_000_000_000L);
        final long start = System.nanoTime();
        final long deadline = start + durationNanos;

        long callsA = 0, callsB = 0, callsC = 0;

        // Round-robin A->B->C; only complete full cycles so counts remain equal
        while (true) {
            if (System.nanoTime() >= deadline) break;

            // A
            SINK_LONG ^= workA(callsA);
            callsA++;

            // Check between functions to avoid overshooting too much
            if (System.nanoTime() >= deadline) { callsA--; break; }

            // B
            SINK_LONG ^= workB(callsB);
            callsB++;

            if (System.nanoTime() >= deadline) { callsA--; callsB--; break; }

            // C
            SINK_DBL += workC(callsC);
            callsC++;

            if (System.nanoTime() >= deadline) { callsA--; callsB--; callsC--; break; }
        }

        // Ensure exactly equal counts (drop any partial cycle if timing cut it short)
        long min = Math.min(callsA, Math.min(callsB, callsC));
        callsA = callsB = callsC = min;

        long elapsedNanos = System.nanoTime() - start;
        System.out.println("Elapsed: " + (elapsedNanos / 1_000_000) + " ms");
        System.out.println("Calls: A=" + callsA + " B=" + callsB + " C=" + callsC + " (equal)");
        System.out.println("Sinks: long=" + SINK_LONG + " double=" + String.format(Locale.ROOT, "%.6f", SINK_DBL));
        // WASTE_DBL intentionally not printed; it's only to prevent optimization.
    }

    // A: expensive string manipulation
    private static long workA(long iter) {
        // Mix iteration to avoid identical strings each time
        String base = "The_quick_brown_fox_jumps_over_the_lazy_dog_" + iter;

        long h = 1469598103934665603L; // FNV-1a-ish mix
        for (int round = 0; round < 500; round++) {
            String s1 = new StringBuilder(base).reverse().append('_').append(round).toString();
            String s2 = s1.toUpperCase(Locale.ROOT).replace('_', '-');
            String s3 = s2 + "::" + Integer.toHexString(s2.hashCode());

            // Byte-level churn
            byte[] bytes = s3.getBytes(StandardCharsets.UTF_8);
            for (byte b : bytes) {
                h ^= (b & 0xFF);
                h *= 1099511628211L;
            }

            // More string churn
            String[] parts = s3.split("::");
            base = parts[0] + "_" + parts[1] + "_" + (h & 0xFFFF);
        }
        return h;
    }

    // B: computationally expensive memcpy (large arraycopy + light checksum)
    private static long workB(long iter) {
        int chunk = 256 * 1024; // 256 KiB
        int copies = 32;        // 32 * 256KiB ~= 8MiB copied per call

        // Offset shifts to avoid copying identical regions each call
        int off = (int) ((iter * 1315423911L) & (MEM_SIZE - 1));
        off = off & ~(chunk - 1); // align to chunk

        for (int i = 0; i < copies; i++) {
            int srcOff = (off + i * chunk) % (MEM_SIZE - chunk);
            int dstOff = (srcOff ^ 0x5A5A5A) % (MEM_SIZE - chunk);
            System.arraycopy(SRC, srcOff, DST, dstOff, chunk);
        }

        // Touch a few bytes so it isn't optimized away
        long sum = 0;
        for (int i = 0; i < 4096; i += 64) {
            sum = (sum * 1315423911L) + (DST[(off + i) % MEM_SIZE] & 0xFF);
        }
        return sum;
    }

    // C: floating point / matrix multiplications (INTENTIONALLY SLOW)
    private static double workC(long iter) {
        // Naive NxN multiply repeated a few times
        double total = 0.0;
        int reps = 6;

        for (int r = 0; r < reps; r++) {
            // OUT = M1 * M2
            for (int i = 0; i < N; i++) {
                // (deliberately avoid caching row references to make access a bit worse)
                for (int j = 0; j < N; j++) {
                    double acc = 0.0;
                    for (int k = 0; k < N; k++) {
                        double prod = M1[i][k] * M2[k][j];
                        acc += prod;

                        // Intentional inefficiency: extra transcendentals in the inner loop.
                        // WASTE_DBL is volatile so the JIT can't discard this work.
                        WASTE_DBL += (Math.sin(prod) + Math.cos(prod)) * 1e-12;
                    }
                    OUT[i][j] = acc;
                }
            }

            // Fold some results into total, and slightly perturb inputs so repeats differ
            int t = (int) (iter + r);
            int ii = (t * 17) & (N - 1);
            int jj = (t * 31) & (N - 1);
            total += OUT[ii][jj];

            double tweak = (total * 1e-9) + 1e-12;
            M1[ii][jj] += tweak;
            M2[jj][ii] -= tweak;
        }
        return total;
    }
}
