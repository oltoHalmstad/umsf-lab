# Host build of the portable libraries + unit tests (no PlatformIO needed).
#   make            build and run tests
#   make vectors    regenerate ../../test_vectors.json and ../../examples/mqtt_samples.jsonl
#   make clean
ROOT    := ../..
LIBS    := $(ROOT)/lib
BUILD   := build
CC      ?= gcc
CXX     ?= g++
WARN    := -Wall -Wextra -Werror
CFLAGS  := -std=c99 -O2 $(WARN) -pedantic
CXXFLAGS:= -std=c++17 -O2 $(WARN)
INC     := -I$(LIBS)/umsf_proto/src -I$(LIBS)/umsf_buffer/src -I$(LIBS)/umsf_features/src -I$(LIBS)/umsf_gwcore/src -I.

C_SRC   := $(wildcard $(LIBS)/umsf_proto/src/*.c)
LIB_CXX := $(wildcard $(LIBS)/umsf_features/src/*.cpp)
TESTS   := $(wildcard test_*.cpp)

LIB_OBJ := $(patsubst $(LIBS)/%.c,$(BUILD)/lib/%.o,$(C_SRC)) $(patsubst $(LIBS)/%.cpp,$(BUILD)/lib/%.o,$(LIB_CXX))
TEST_OBJ:= $(patsubst %.cpp,$(BUILD)/%.o,$(TESTS))

.PHONY: all test vectors clean
all: test

$(BUILD)/lib/%.o: $(LIBS)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(INC) -c $< -o $@
$(BUILD)/lib/%.o: $(LIBS)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(INC) -c $< -o $@
$(BUILD)/%.o: %.cpp umsf_test.h
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(INC) -c $< -o $@

$(BUILD)/umsf_tests: $(LIB_OBJ) $(TEST_OBJ)
	$(CXX) $^ -o $@ -lm

test: $(BUILD)/umsf_tests
	./$(BUILD)/umsf_tests

$(BUILD)/gen_vectors: $(ROOT)/tools/gen_vectors/gen_vectors.cpp $(LIB_OBJ)
	$(CXX) $(CXXFLAGS) $(INC) $^ -o $@ -lm

vectors: $(BUILD)/gen_vectors
	@mkdir -p $(ROOT)/examples
	./$(BUILD)/gen_vectors $(ROOT)/test_vectors.json $(ROOT)/examples/mqtt_samples.jsonl

clean:
	rm -rf $(BUILD)
