# OUTPUT_DIR := output
BINARY_NAME := qemu_generator
LIB_DIR := lib
PROGRAM_DIR := ..

all: build

build:
	@mkdir -p $(LIB_DIR)
	# go build -o $(OUTPUT_DIR)/$(BINARY_NAME) .
	go build -buildmode=c-archive -o $(LIB_DIR)/libQemuGen.a ./src
	go build -buildmode=c-shared -o $(LIB_DIR)/libQemuGen.so ./src
	cp $(LIB_DIR)/libQemuGen.h $(PROGRAM_DIR)/inc
	cp $(LIB_DIR)/libQemuGen.a $(PROGRAM_DIR)/src

clean:
	rm -rf $(LIB_DIR)
	rm -f $(PROGRAM_DIR)/inc/libQemuGen*
	rm -f $(PROGRAM_DIR)/src/libQemuGen*

.PHONY: all build clean
