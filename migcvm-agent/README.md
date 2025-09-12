# MIGVM 

## 
MIGVMTSI

## 
1. 
2. 
```bash
chmod +x build.sh
./build.sh
```

`build``migvm_agent`

### 
`--debug`
```bash
./build.sh --debug
```

socket-send
```bash
./build.sh --build-debug-tool
```

## 

```bash
./build/migvm_agent
```

## 
```
.
 CMakeLists.txt        # CMake
 build.sh              # 
 migvm_agent.c         # 
 debug/                # 
    socket-send.c     # 
    tsi-test.c        # TSI
 migcvm_tsi/           # TSI
    migcvm_tsi.c
    tsi.h
 socket_agent/         # 
     host_socket_agent.c
     socket_agent.h
```

## 
DH
1. xxxxxx

## 
- CMake (>= 3.10)
- GNU Make
- C (GCCClang)

---

# MIGVM Agent

## Overview
The MIGVM Agent is a virtual machine migration agent that provides socket communication and TSI (Trusted Service Interface) capabilities.

## Build Instructions
1. Clone the repository
2. Run the build script:
```bash
chmod +x build.sh
./build.sh
```

The executable will be generated in the `build` directory as `migvm_agent`.

### Debug Mode
To build in debug mode, add the `--debug` parameter:
```bash
./build.sh --debug
```

Debug tool (socket-send) can be built separately:
```bash
./build.sh --build-debug-tool
```

## Run Instructions
Execute the agent with:
```bash
./build/migvm_agent
```

## Directory Structure
```
.
 CMakeLists.txt        # CMake configuration
 build.sh              # Build automation script
 migvm_agent.c         # Main application
 debug/                # Debug tools
    socket-send.c     # Socket test tool
    tsi-test.c        # TSI test tool
 migcvm_tsi/           # TSI implementation
    migcvm_tsi.c
    tsi.h
 socket_agent/         # Socket communication
     host_socket_agent.c
     socket_agent.h
```

## Secure Communication
The agent uses DH key exchange to establish secure channels:
1. xxxxxx

## Dependencies
- CMake (>= 3.10)
- GNU Make
- C compiler (GCC or Clang)

## License
This project is licensed under the MIT License.

