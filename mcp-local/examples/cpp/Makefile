CXX = g++
CXXFLAGS = -O3 -march=native -fopenmp -Wall -Wextra -std=c++17

# Detect architecture
ARCH := $(shell uname -m)

ifeq ($(ARCH),x86_64)
    CXXFLAGS += -mavx2 -mfma
    $(info Building for x86-64 with AVX2 support)
else ifeq ($(ARCH),aarch64)
    # ARM-specific flags
    CXXFLAGS += -mcpu=native
    $(info Building for ARM64/AArch64)
    $(warning Intel intrinsics will not be available!)
endif

TARGET = particle_sim
OBJS = main.o simulator.o

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^

main.o: main.cpp simulator.h
	$(CXX) $(CXXFLAGS) -c $< -o $@

simulator.o: simulator.cpp simulator.h
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

run: $(TARGET)
	./$(TARGET)

# Target to attempt build and show errors
test-build:
	@echo "=== Attempting to build on current architecture ==="
	@make clean
	@make 2>&1 | tee build.log
	@echo "=== Build complete. Check build.log for any errors ==="

.PHONY: all clean run test-build