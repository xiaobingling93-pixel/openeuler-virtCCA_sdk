// Copyright (c) 2018 HyperHQ Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package main

import (
	"context"
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"gopkg.in/yaml.v3"
	"io/ioutil"
	"path/filepath"
	goruntime "runtime"
	"strconv"
	"strings"
	"sync"
	"time"
	"C"
	"encoding/json"
	"math"

	"bufio"
	"os/exec"
	"regexp"

	"github.com/pbnjay/memory"

	"github.com/BurntSushi/toml"
	"github.com/containernetworking/plugins/pkg/ns"
	gt_config "github.com/kata-containers/kata-containers/src/runtime/pkg/device/config"
	drivers "github.com/kata-containers/kata-containers/src/runtime/pkg/device/drivers"
	"github.com/kata-containers/kata-containers/src/runtime/pkg/govmm"
	govmmQemu "qemu_generator/src/qemu"
	hv "github.com/kata-containers/kata-containers/src/runtime/pkg/hypervisors"
	"github.com/kata-containers/kata-containers/src/runtime/pkg/uuid"
	vc "github.com/kata-containers/kata-containers/src/runtime/virtcontainers"
	"github.com/kata-containers/kata-containers/src/runtime/virtcontainers/types"
	utils "github.com/kata-containers/kata-containers/src/runtime/virtcontainers/utils"
	"github.com/pkg/errors"
	"github.com/sirupsen/logrus"
	"github.com/NVIDIA/go-nvlib/pkg/nvpci"
	"github.com/vishvananda/netns"
	"github.com/vishvananda/netlink"
	vcAnnotations "github.com/kata-containers/kata-containers/src/runtime/virtcontainers/pkg/annotations"
)

// ********** kata-containers/src/libs/kata-types/src/annotations/mod.rs **********
const (
	// The annotation key to fetch runtime configuration file.
	SANDBOX_CFG_PATH_KEY = "io.katacontainers.config_path";

	// A sandbox annotation for the memory assigned for a VM by the hypervisor.
	KATA_ANNO_CFG_HYPERVISOR_DEFAULT_MEMORY = "io.katacontainers.config.hypervisor.default_memory"

	// A sandbox annotation for passing the default vCPUs assigned for a VM by the hypervisor.
	KATA_ANNO_CFG_HYPERVISOR_DEFAULT_VCPUS = "io.katacontainers.config.hypervisor.default_vcpus"

	// A sandbox annotation for passing additional guest kernel parameters.
	KATA_ANNO_CFG_HYPERVISOR_KERNEL_PARAMS = "io.katacontainers.config.hypervisor.kernel_params"

)

func calculateSandboxCPUs(podConfig *PodConfig) (float32, error) {
	totalCPUs := float64(0)

	for _, c := range podConfig.Spec.Containers {
		cpuStr := c.Resources.Limits.CPU
		if cpuStr == "" {
			continue
		}

		// deal input format like "1000m","500m" etc.
		if strings.HasSuffix(cpuStr, "m") {
			milliCores, err := strconv.ParseFloat(strings.TrimSuffix(cpuStr, "m"), 64)
			if err != nil {
				return 0, fmt.Errorf("invalid millicore format '%s' in container %s: %v",
					cpuStr, c.Name, err)
			}
			totalCPUs += milliCores / 1000.0
			continue
		}

		// deal input format like "2","1.5" etc.
		cores, err := strconv.ParseFloat(cpuStr, 64)
		if err != nil {
			return 0, fmt.Errorf("invalid cpu format '%s' in container %s: %v",
				cpuStr, c.Name, err)
		}
		totalCPUs += cores
	}

	roundedCPUs := math.Ceil(totalCPUs)
	return float32(roundedCPUs), nil
}

func calculateSandboxMemory(config_pod *PodConfig) (uint32, error) {
	totalMemoryMiB := 0.0

	for _, container := range config_pod.Spec.Containers {
		memoryStr := container.Resources.Limits.Memory
		if memoryStr == "" {
			continue
		}

		memoryMiB, err := parseMemoryToMiB(memoryStr)
		if err != nil {
			log.Printf("Invalid container.Resources.Limits.Memory configuration:'%s': %v.", memoryStr, err)
			continue
		}
		totalMemoryMiB += memoryMiB
	}

	fmt.Println("calculateSandboxMemory res: ", int(math.Round(totalMemoryMiB)))

	return uint32(math.Round(totalMemoryMiB)), nil
}

func parseMemoryToMiB(memoryStr string) (float64, error) {
	// Separate the numerical part from the unit part
	numPart, unitPart := splitMemoryString(memoryStr)

	// Parsing numeric parts (supports integers and decimals)
	value, err := strconv.ParseFloat(numPart, 64)
	if err != nil {
		return 0, err
	}

	switch strings.ToLower(unitPart) {
	case "ki", "kib":
		return value / 1024, nil // KiB  MiB: /1024
	case "mi", "mib":
		return value, nil // MiB
	case "gi", "gib":
		return value * 1024, nil // GiB  MiB: *1024
	case "ti", "tib":
		return value * 1024 * 1024, nil // TiB  MiB: *1024*1024
	case "k", "kb":
		return value * 1000 / (1024 * 1024), nil // KB  MiB: *1000/1048576
	case "m", "mb":
		return value * 1000000 / (1024 * 1024), nil
	case "g", "gb":
		return value * 1000000000 / (1024 * 1024), nil
	case "":
		return value / (1024 * 1024), nil // If no unit is specified, the default unit is bytes.
	default:
		return value, fmt.Errorf("Unit abnormal, illegal input")
	}
}

func splitMemoryString(s string) (numPart, unitPart string) {
	// Find the position of the first non-numeric (and non-decimal point) character.
	idx := 0

	for ; idx < len(s); idx++ {
		c := s[idx]
		if !((c >= '0' && c <= '9') || c == '.') {
			break
		}
	}

	if idx == 0 {
		return "", s // No numerical part, exceptional case
	}
	return s[:idx], s[idx:]
}

//export GenerateQemuInstr
func GenerateQemuInstr(input_1 *C.char, input_2 *C.char) (int, uint32, *C.char, *C.char, *C.char) {
    // change c string to go
    kata_config_path := C.GoString(input_1)
	pod_config_path := C.GoString(input_2)
	var kataConfigPath string
	var podConfigPath string
	var podConfig *PodConfig

	//read the kata config path
	if kata_config_path == "" {
		log.Fatalf("Error: In GenerateQemuInstr-lib, kata config-path is not setup")
	} else {
		fmt.Printf("Info: In GenerateQemuInstr-lib, kata config-path is setup as: %v\n", kata_config_path)
		kataConfigPath = kata_config_path
	}

	if pod_config_path == "" {
		log.Fatalf("Error: In GenerateQemuInstr-lib, k8s config-path is not setup")
	} else {
		fmt.Printf("Info: In GenerateQemuInstr-lib, k8s config-path is setup as: %v\n", pod_config_path)
		podConfigPath = pod_config_path
	}

	// check the yaml file is exist
	if _, err := os.Stat(podConfigPath); os.IsNotExist(err) {
		log.Fatalf("Error: In GenerateQemuInstr-lib, k8s config YAML file not found: %v\n", podConfigPath)
	} else {
		fmt.Println("Parsing parameters from the k8s config file:", podConfigPath, "...")
		var err_pod_cfg error
		podConfig, err_pod_cfg = ReadPodConfig(podConfigPath)
		// update the kataConfigPath by reading the pod.yaml
		if err_pod_cfg != nil {
			fmt.Printf("Warning: Failed to parse pod config: %v\n", err)
		}
	}

	// update kataConfigPath
	if path, exists := podConfig.Metadata.Annotations[SANDBOX_CFG_PATH_KEY]; exists {
		kataConfigPath = path
	}

	// check the toml file is exist
	if _, err := os.Stat(kataConfigPath); os.IsNotExist(err) {
		log.Fatalf("Error: In GenerateQemuInstr-lib, kata config TOML file not found: %v\n", kataConfigPath)
	} else {
		fmt.Println("Parsing parameters from the config file:", kataConfigPath, "...")
	}

	// init the qemu-hypervisor dummy config
	var toml_config struct {
		Config_h struct {
			Hypervisor hypervisor `toml:"qemu"`
		} `toml:"hypervisor"`
		Config_a struct {
			Agent agent `toml:"kata"`
		} `toml:"agent"`
	}

	// read the toml into struct toml_config
	if _, err := toml.DecodeFile(kataConfigPath, &toml_config); err != nil {
		log.Fatalf("Failed to parse the coco config TOML file: %v", err)
	}

	hypervisorConfig, err := newQemuHypervisorConfig(toml_config.Config_h.Hypervisor)
	if err != nil {
		log.Fatalf("Failed to create hypervisor config while reading the coco config TOML file: %v\n", err)
	}

	agentConfig,err := updateRuntimeConfigAgent(toml_config.Config_a.Agent)
	if err != nil {
		log.Fatalf("Failed to create agent config while reading the coco config TOML file: %v\n", err)
	}

	hypervisorConfig, err = SetKernelParams(hypervisorConfig, agentConfig, podConfig)
	if err != nil {
		log.Fatalf("Error update kernel params while reading the coco config TOML file: %v\n", err)
	}

	// update default_memory, default_vcpu based on podConfig(pod.yaml)
	hypervisorConfig, err = ParsePodConfig(hypervisorConfig, podConfig)
	if err != nil {
		log.Fatalf("update default_memory, default_vcpu based on pod.yaml failed: %v\n", err)
	}

	//Passing kata config to qemu-config struct
	var config_q *qemu = new(qemu)
	err_c := config_q.CreateVM("dtb-baseline-00", &hypervisorConfig)

	if err_c != nil {
		log.Printf("Error passing hypervisor config to qemuconfig while reading the coco config TOML file: %v\n", err_c)
		return 0, 0, nil, nil, nil
	} else {
		fmt.Println("Passing kata config to qemu successfully while reading the coco config TOML file.")
	}

	var covertQMPSockets []QMPSocket
	for _, socket := range config_q.qemuConfig.QMPSockets {
		covertQMPSockets = append(covertQMPSockets, QMPSocket{Type: QMPSocketType(socket.Protocol), Protocol: MonitorProtocol(socket.Protocol), FD: socket.FD, Name: socket.Name, Server: socket.Server, NoWait: socket.NoWait})
	}
	covertDevices := make([]Device,len(config_q.qemuConfig.Devices))
	for i,device := range config_q.qemuConfig.Devices {
		covertDevices[i] = &DeviceAdapter{device}
	}
	var covertFwCfg []FwCfg
	for _, fwcfg := range config_q.qemuConfig.FwCfg {
		covertFwCfg = append(covertFwCfg, FwCfg{Name: fwcfg.Name, File: fwcfg.File, Str: fwcfg.Str})
	}
	var covertiothread []IOThread
	for _, iothread := range config_q.qemuConfig.IOThreads {
		covertiothread = append(covertiothread, IOThread{ID: iothread.ID})
	}

	logger := &SimpleLogger{}
	config_output := Config{
		Path:           config_q.qemuConfig.Path,
		Uid:            config_q.qemuConfig.Uid,
		Gid:            config_q.qemuConfig.Gid,
		Groups:         config_q.qemuConfig.Groups,
		Name:           config_q.qemuConfig.Name,
		UUID:           config_q.qemuConfig.UUID,
		CPUModel:       config_q.qemuConfig.CPUModel,
		SeccompSandbox: config_q.qemuConfig.SeccompSandbox,
		Machine:        Machine(config_q.qemuConfig.Machine),
		QMPSockets:     covertQMPSockets,
		Devices:        covertDevices,
		RTC:            RTC{RTCBaseType(config_q.qemuConfig.RTC.Base),RTCClock(config_q.qemuConfig.RTC.Clock),RTCDriftFix(config_q.qemuConfig.RTC.DriftFix)},
		VGA:            config_q.qemuConfig.VGA,
		Kernel:         Kernel(config_q.qemuConfig.Kernel),
		Memory:         Memory(config_q.qemuConfig.Memory),     //{Size:"2048M",Slots:10,MaxMem:"2975M",Path:"/dev/shm"},
		SMP:            SMP(config_q.qemuConfig.SMP),           //{CPUs:1,Cores:1,Threads:1,Sockets:4,MaxCPUs:4},
		GlobalParam:    config_q.qemuConfig.GlobalParam,        //"kvm-pit.lost_tick_policy=discard",
		Knobs:          Knobs(config_q.qemuConfig.Knobs),       //{NoUserConfig:true,NoDefaults:true,NoGraphic:true,Daemonize:false,HugePages:false,MemPrealloc:false,FileBackedMem:true,MemShared:true,Mlock:false,Stopped:false,NoReboot:true,NoShutdown:false,IOMMUPlatform:false},
		Bios:           config_q.qemuConfig.Bios,               //"",
		PFlash:         config_q.qemuConfig.PFlash,             //[]string{""},
		Incoming:       Incoming(config_q.qemuConfig.Incoming), //{MigrationType:0,FD:nil,Exec:""},
		fds:            config_q.qemuConfig.GetFds(),//[]*os.File{},
		FwCfg:          covertFwCfg,                 //[]FwCfg{},
		IOThreads:      covertiothread,              //[]IOThread{},
		PidFile:        config_q.qemuConfig.PidFile, //"/run/vc/vm/hello566/pid",
		qemuParams:     config_q.qemuConfig.GetQEMUParams(),//[]string{""},
		Debug:		    config_q.qemuConfig.Debug,
	}

	fmt.Println("SMP.VCPU, Memory, Kernel_params: ", config_output.SMP.CPUs, config_output.Memory.Size, config_output.Kernel.Params);

	qemu_string, err := LaunchQemu(config_output, logger)

	if err != nil {
		fmt.Printf("LaunchQemu failed: %v\n", err)
	} else {
		fmt.Println("QEMU instruction generate succesfully, qemu cmd returned by LaunchQemu: ", qemu_string)
	}

	return 1, config_output.SMP.CPUs, C.CString(qemu_string), C.CString(hypervisorConfig.HypervisorPath), C.CString(hypervisorConfig.KernelPath)
}

func parsePodKernelParams(paramsStr string) []Param {
	var params []Param
	pairs := strings.Fields(paramsStr)
	for _, pair := range pairs {
		parts := strings.SplitN(pair, "=", 2)
		if len(parts) == 2 {
			params = append(params, Param{Key: parts[0], Value: parts[1]})
		} else if len(parts) == 1 {
			params = append(params, Param{Key: parts[0], Value: ""})
		}
	}
	return params
}

func SetKernelParams(config HypervisorConfig, config_a KataAgentConfig, config_pod *PodConfig) (HypervisorConfig, error) {
	var defaultKernelParams []Param
	defaultKernelParams = getCVMKernelParams(needSystemd(config))

	if config.Debug {
		strParams := SerializeParams(defaultKernelParams, "=")
		formatted := strings.Join(strParams, " ")
		kataUtilsLogger.WithField("default-kernel-parameters", formatted).Debug()
	}

	// reset
	userKernelParams := config.KernelParams
	config.KernelParams = []Param{}

	// first, add default values
	for _, p := range defaultKernelParams {
		if err := config.AddKernelParam(p); err != nil {
			return config, err
		}
	}

	// set the scsi scan mode to none for virtio-scsi
	if config.BlockDeviceDriver == gt_config.VirtioSCSI {
		p := Param{
			Key:   "scsi_mod.scan",
			Value: "none",
		}
		if err := config.AddKernelParam(p); err != nil {
			return config, err
		}
	}

	// next, check for agent specific kernel params
	params := KataAgentKernelParams(config_a)

	for _, p := range params {
		if err := config.AddKernelParam(p); err != nil {
			return config, err
		}
	}

	// now re-add the user-specified values so that they take priority.
	for _, p := range userKernelParams {
		if err := config.AddKernelParam(p); err != nil {
			return config, err
		}
	}

	// append PodKernelParams to HypervisorConfig's kernel_params
	if config_pod_params, exists := config_pod.Metadata.Annotations[KATA_ANNO_CFG_HYPERVISOR_KERNEL_PARAMS]; exists {
		PodKernelParams := parsePodKernelParams(config_pod_params)
		config.KernelParams = append(config.KernelParams, PodKernelParams...)
	}

	return config, nil
}

func ParsePodConfig(config HypervisorConfig, config_pod *PodConfig) (HypervisorConfig, error) {
	// update default_vcpu
	if annoVCPU, exists := config_pod.Metadata.Annotations[KATA_ANNO_CFG_HYPERVISOR_DEFAULT_VCPUS]; exists {
		vcpu, err := strconv.ParseUint(annoVCPU, 10, 32)
		if err != nil {
			log.Printf("Invalid annotation default vCPU input '%s': %v.", annoVCPU, err)
		} else {
			config.NumVCPUsF = float32(vcpu)
		}
	}

	// update default_vcpu based on containers.resources.limit
	if limitCPU, err := calculateSandboxCPUs(config_pod); err == nil {
		config.NumVCPUsF += limitCPU
	}

	// static_sandbox_resource_mgmt=true -> do not support CPU and/or memory hotplug
	config.DefaultMaxVCPUs = uint32(config.NumVCPUsF)

	// update default_memory
	if annoMemory, exists := config_pod.Metadata.Annotations[KATA_ANNO_CFG_HYPERVISOR_DEFAULT_MEMORY]; exists {
		memory := uint32(0)
		numPart, unitPart := splitMemoryString(annoMemory)

		if numPart != "" {
			value, err := strconv.ParseFloat(numPart, 32)
			if err != nil {
				log.Printf("Invalid annotation default memory input '%s': %v.", annoMemory, err)
			} else {
				switch strings.ToUpper(unitPart) {
				case "", "M", "MB":
					memory = uint32(math.Round(value))
				case "G", "GB":
					memory = uint32(math.Round(value * 1024))
				default:
					log.Printf("Invalid annotation default memory uint '%s': %v.", unitPart, err)
				}
			}
		}

		if memory != 0 {
			config.MemorySize = memory
		}
	}

	if limitMemory, err := calculateSandboxMemory(config_pod); err == nil && limitMemory != 0 {
		config.MemorySize += limitMemory
	}

	return config, nil
}

// variables rather than consts to allow tests to modify them
var (
	kvmDevice = "/dev/kvm"
)

func GetEndpointsNum() (int, error) {
	netnsHandle, err := netns.GetFromPath("/etc/netplan/50-cloud-init.yaml")
	if err != nil {
		return 0, err
	}
	defer netnsHandle.Close()

	netlinkHandle, err := netlink.NewHandleAt(netnsHandle)
	if err != nil {
		return 0, err
	}
	defer netlinkHandle.Close()

	linkList, err := netlinkHandle.LinkList()
	if err != nil {
		return 0, err
	}

	return len(linkList), nil
}

const (
	// unix socket type of console
	consoleProtoUnix = "unix"

	// pty type of console.
	consoleProtoPty = "pty"
)

// GetVMConsole builds the path of the console where we can read logs coming
// from the sandbox.
func (q *qemu) GetVMConsole(id string) (string, string, error) {
	consoleURL, err := utils.BuildSocketPath(q.config.VMStorePath, id, consoleSocket)
	if err != nil {
		return consoleProtoUnix, "", err
	}
	return consoleProtoUnix, consoleURL, nil
}

func (q *qemu) appendImage(devices []govmmQemu.Device) ([]govmmQemu.Device, error) {
	imagePath, err := q.config.ImageAssetPath()
	if err != nil {
		return nil, err
	}

	if imagePath != "" {
		devices, err = q.arch.appendImage(devices, imagePath)
		if err != nil {
			return nil, err
		}
	}

	return devices, nil
}

func main() { }

// Can be expanded as needed
type PodConfig struct {
	APIVersion string            `yaml:"apiVersion"`
	Kind       string            `yaml:"kind"`
	Metadata   struct {
		Name        string            `yaml:"name"`
		Annotations map[string]string `yaml:"annotations"`
	} `yaml:"metadata"`
	Spec struct {
		Containers []struct {
			Name             string   `yaml:"name"`
			Image            string   `yaml:"image"`
			ImagePullPolicy  string   `yaml:"imagePullPolicy"`
			Command          []string `yaml:"command"`
			TTY              bool     `yaml:"tty"`
			Resources        struct {
				Limits struct {
					Memory string `yaml:"memory"`
					CPU    string `yaml:"cpu"`
				} `yaml:"limits"`
			} `yaml:"resources"`
		} `yaml:"containers"`
	} `yaml:"spec"`
}


func ReadPodConfig(configPath string) (*PodConfig, error) {
	yamlFile, err := ioutil.ReadFile(configPath)
	if err != nil {
		fmt.Printf("Failed to read YAML file: %v", err)
		return nil, err
	}

    var config PodConfig
	err = yaml.Unmarshal(yamlFile, &config)
	if err != nil {
		fmt.Printf("Failed to unmarshal YAML: %v", err)
		return nil, err
	}
	return &config, nil
}

type DeviceAdapter struct {
	device govmmQemu.Device
}
func (d *DeviceAdapter) Valid() bool {
	return d.device.Valid()
}


func (d *DeviceAdapter) QemuParams(config *Config) []string {
	govmmConfig := &govmmQemu.Config{}
	return d.device.QemuParams(govmmConfig)
}

type RTCAdapter struct {
	rtc govmmQemu.RTC
}
func (d *RTCAdapter) Valid() bool {
	return d.rtc.Valid()
}

// QMPLog interface dummy
type SimpleLogger struct{}

// QMPLog  V
func (s *SimpleLogger) V(level int32) bool {
	return level <= 2 //  only print less than 2 log level
}

// QMPLog  Infof
func (s *SimpleLogger) Infof(format string, args ...interface{}) {
	fmt.Printf("[INFO] "+format+"\n", args...)
}

// QMPLog  Warningf
func (s *SimpleLogger) Warningf(format string, args ...interface{}) {
	fmt.Printf("[WARNING] "+format+"\n", args...)
}

// QMPLog  Errorf
func (s *SimpleLogger) Errorf(format string, args ...interface{}) {
	fmt.Printf("[ERROR] "+format+"\n", args...)
}

// ********** kata-containers\src\runtime\virtcontainers\utils\utils.go **********
// SupportsVsocks returns true if vsocks are supported, otherwise false
func SupportsVsocks() (bool, error) {
	if _, err := os.Stat(VHostVSockDevicePath); err != nil {
		return false, fmt.Errorf("host system doesn't support vsock: %v", err)
	}

	return true, nil
}

// LaunchQemu can be used to launch a new qemu instance.
//
// The Config parameter contains a set of qemu parameters and settings.
//
// See LaunchCustomQemu for more information.
func LaunchQemu(config Config, logger QMPLog) (string, error) {

	config.appendName()
	config.appendUUID()
	config.appendMachine()
	config.appendCPUModel()
	config.appendQMPSockets()
	config.appendMemory()
	config.appendDevices(logger)
	config.appendRTC()
	config.appendGlobalParam()
	config.appendPFlashParam()
	config.appendVGA()
	config.appendKnobs()
	config.appendKernel()
	config.appendBios()
	config.appendIOThreads()
	config.appendIncoming()
	config.appendPidFile()
	config.appendFwCfg(logger)
	config.appendSeccompSandbox()

	if err := config.appendCPUs(); err != nil {
		return "",err
	}

	outputFilePath := "qemu_params.conf"

	// input the config.qemuParams into the outputFilePath
	file, err := os.Create(outputFilePath)
	if err != nil {
		fmt.Printf("Failed to create log file: %v\n", err)
		return "",fmt.Errorf("failed to create qemu_params log file: %v", err)
	}
	defer file.Close()

	paramsStr := strings.Join(config.qemuParams, " ")
	_, err = fmt.Fprintf(file, "%s", paramsStr)
	if err != nil {
		fmt.Printf("Failed to write qemu params to file: %v\n", err)
		return "",fmt.Errorf("failed to write qemu params to file: %v", err)
	}

	return paramsStr,nil
}

// ********** kata-containers\src\runtime\pkg\govmm\qemu\qemu.go **********
// Machine describes the machine type qemu will emulate.
type Machine struct {
	// Type is the machine type to be used by qemu.
	Type string

	// Acceleration are the machine acceleration options to be used by qemu.
	Acceleration string

	// Options are options for the machine type
	// For example gic-version=host and usb=off
	Options string
}

const (
	// MachineTypeMicrovm is the QEMU microvm machine type for amd64
	MachineTypeMicrovm string = "microvm"
)

const (
	// Well known vsock CID for host system.
	// https://man7.org/linux/man-pages/man7/vsock.7.html
	VsockHostCid uint64 = 2
)

// Device is the qemu device interface.
type Device interface {
	Valid() bool
	QemuParams(config *Config) []string
}

// DeviceDriver is the device driver string.
type DeviceDriver string

const (
	// LegacySerial is the legacy serial device driver
	LegacySerial DeviceDriver = "serial"

	// NVDIMM is the Non Volatile DIMM device driver.
	NVDIMM DeviceDriver = "nvdimm"

	// VirtioNet is the virtio networking device driver.
	VirtioNet DeviceDriver = "virtio-net"

	// VirtioNetPCI is the virt-io pci networking device driver.
	VirtioNetPCI DeviceDriver = "virtio-net-pci"

	// VirtioNetCCW is the virt-io ccw networking device driver.
	VirtioNetCCW DeviceDriver = "virtio-net-ccw"

	// VirtioBlock is the block device driver.
	VirtioBlock DeviceDriver = "virtio-blk"

	// Console is the console device driver.
	Console DeviceDriver = "virtconsole"

	// Virtio9P is the 9pfs device driver.
	Virtio9P DeviceDriver = "virtio-9p"

	// VirtioSerial is the serial device driver.
	VirtioSerial DeviceDriver = "virtio-serial"

	// VirtioSerialPort is the serial port device driver.
	VirtioSerialPort DeviceDriver = "virtserialport"

	// VirtioRng is the paravirtualized RNG device driver.
	VirtioRng DeviceDriver = "virtio-rng"

	// VirtioBalloon is the memory balloon device driver.
	VirtioBalloon DeviceDriver = "virtio-balloon"

	//VhostUserSCSI represents a SCSI vhostuser device type.
	VhostUserSCSI DeviceDriver = "vhost-user-scsi"

	//VhostUserNet represents a net vhostuser device type.
	VhostUserNet DeviceDriver = "virtio-net"

	//VhostUserBlk represents a block vhostuser device type.
	VhostUserBlk DeviceDriver = "vhost-user-blk"

	//VhostUserFS represents a virtio-fs vhostuser device type
	VhostUserFS DeviceDriver = "vhost-user-fs"

	// PCIBridgeDriver represents a PCI bridge device type.
	PCIBridgeDriver DeviceDriver = "pci-bridge"

	// PCIePCIBridgeDriver represents a PCIe to PCI bridge device type.
	PCIePCIBridgeDriver DeviceDriver = "pcie-pci-bridge"

	// VfioPCI is the vfio driver with PCI transport.
	VfioPCI DeviceDriver = "vfio-pci"

	// VfioCCW is the vfio driver with CCW transport.
	VfioCCW DeviceDriver = "vfio-ccw"

	// VfioAP is the vfio driver with AP transport.
	VfioAP DeviceDriver = "vfio-ap"

	// VHostVSockPCI is a generic Vsock vhost device with PCI transport.
	VHostVSockPCI DeviceDriver = "vhost-vsock-pci"

	// PCIeRootPort is a PCIe Root Port, the PCIe device should be hotplugged to this port.
	PCIeRootPort DeviceDriver = "pcie-root-port"

	// PCIeSwitchUpstreamPort is a PCIe switch upstream port
	// A upstream port connects to a PCIe Root Port
	PCIeSwitchUpstreamPort DeviceDriver = "x3130-upstream"

	// PCIeSwitchDownstreamPort is a PCIe switch downstream port
	// PCIe devices can be hot-plugged to the downstream port.
	PCIeSwitchDownstreamPort DeviceDriver = "xio3130-downstream"

	// Loader is the Loader device driver.
	Loader DeviceDriver = "loader"

	// SpaprTPMProxy is used for enabling guest to run in secure mode on ppc64le.
	SpaprTPMProxy DeviceDriver = "spapr-tpm-proxy"
)

func isDimmSupported(config *Config) bool {
	if config != nil && config.Machine.Type == MachineTypeMicrovm {
		return false
	}
	return true
}

// VirtioTransport is the transport in use for a virtio device.
type VirtioTransport string

const (
	// TransportPCI is the PCI transport for virtio device.
	TransportPCI VirtioTransport = "pci"

	// TransportCCW is the CCW transport for virtio devices.
	TransportCCW VirtioTransport = "ccw"

	// TransportMMIO is the MMIO transport for virtio devices.
	TransportMMIO VirtioTransport = "mmio"

	// TransportAP is the AP transport for virtio devices.
	TransportAP VirtioTransport = "ap"
)

// defaultTransport returns the default transport for the current combination
// of host's architecture and QEMU machine type.
func (transport VirtioTransport) defaultTransport(config *Config) VirtioTransport {
	return TransportPCI
}

// isVirtioPCI returns true if the transport is PCI.
func (transport VirtioTransport) isVirtioPCI(config *Config) bool {
	if transport == "" {
		transport = transport.defaultTransport(config)
	}

	return transport == TransportPCI
}

// isVirtioCCW returns true if the transport is CCW.
func (transport VirtioTransport) isVirtioCCW(config *Config) bool {
	if transport == "" {
		transport = transport.defaultTransport(config)
	}

	return transport == TransportCCW
}

func (transport VirtioTransport) isVirtioAP(config *Config) bool {
	if transport == "" {
		transport = transport.defaultTransport(config)
	}

	return transport == TransportAP
}

// getName returns the name of the current transport.
func (transport VirtioTransport) getName(config *Config) string {
	if transport == "" {
		transport = transport.defaultTransport(config)
	}

	return string(transport)
}

// disableModern returns the parameters with the disable-modern option.
// In case the device driver is not a PCI device and it doesn't have the option
// an empty string is returned.
func (transport VirtioTransport) disableModern(config *Config, disable bool) string {
	if !transport.isVirtioPCI(config) {
		return ""
	}

	if disable {
		return "disable-modern=true"
	}

	return "disable-modern=false"
}

// ObjectType is a string representing a qemu object type.
type ObjectType string

const (
	// MemoryBackendFile represents a guest memory mapped file.
	MemoryBackendFile ObjectType = "memory-backend-file"

	// MemoryBackendEPC represents a guest memory backend EPC for SGX.
	MemoryBackendEPC ObjectType = "memory-backend-epc"

	// TDXGuest represents a TDX object
	TDXGuest ObjectType = "tdx-guest"

	// SEVGuest represents an SEV guest object
	SEVGuest ObjectType = "sev-guest"

	// SNPGuest represents an SNP guest object
	SNPGuest ObjectType = "sev-snp-guest"

	// SecExecGuest represents an s390x Secure Execution (Protected Virtualization in QEMU) object
	SecExecGuest ObjectType = "s390-pv-guest"

	// PEFGuest represent ppc64le PEF(Protected Execution Facility) object.
	PEFGuest ObjectType = "pef-guest"
)

// Object is a qemu object representation.
// nolint: govet
type Object struct {
	// Driver is the qemu device driver
	Driver DeviceDriver

	// Type is the qemu object type.
	Type ObjectType

	// ID is the user defined object ID.
	ID string

	// DeviceID is the user defined device ID.
	DeviceID string

	// MemPath is the object's memory path.
	// This is only relevant for memory objects
	MemPath string

	// Size is the object size in bytes
	Size uint64

	// Debug this is a debug object
	Debug bool

	// File is the device file
	File string

	// FirmwareVolume is the configuration volume for the firmware
	// it can be used to split the TDVF/OVMF UEFI firmware in UEFI variables
	// and UEFI program image.
	FirmwareVolume string

	// CBitPos is the location of the C-bit in a guest page table entry
	// This is only relevant for sev-guest objects
	CBitPos uint32

	// ReducedPhysBits is the reduction in the guest physical address space
	// This is only relevant for sev-guest objects
	ReducedPhysBits uint32

	// ReadOnly specifies whether `MemPath` is opened read-only or read/write (default)
	ReadOnly bool

	// Prealloc enables memory preallocation
	Prealloc bool

	// QgsPort defines Intel Quote Generation Service port exposed from the host
	QgsPort uint32

	// SnpIdBlock is the 96-byte, base64-encoded blob to provide the ID Block structure
	// for the SNP_LAUNCH_FINISH command defined in the SEV-SNP firmware ABI (default: all-zero)
	SnpIdBlock string

	// SnpIdAuth is the 4096-byte, base64-encoded blob to provide the ID Authentication Information Structure
	// for the SNP_LAUNCH_FINISH command defined in the SEV-SNP firmware ABI (default: all-zero)
	SnpIdAuth string
}

// Valid returns true if the Object structure is valid and complete.
func (object Object) Valid() bool {
	switch object.Type {
	case MemoryBackendFile:
		return object.ID != "" && object.MemPath != "" && object.Size != 0
	case MemoryBackendEPC:
		return object.ID != "" && object.Size != 0
	case TDXGuest:
		return object.ID != "" && object.File != "" && object.DeviceID != "" && object.QgsPort != 0
	case SEVGuest:
		fallthrough
	case SNPGuest:
		return object.ID != "" && object.File != "" && object.CBitPos != 0 && object.ReducedPhysBits != 0
	case SecExecGuest:
		return object.ID != ""
	case PEFGuest:
		return object.ID != "" && object.File != ""

	default:
		return false
	}
}

// QemuParams returns the qemu parameters built out of this Object device.
func (object Object) QemuParams(config *Config) []string {
	var objectParams []string
	var deviceParams []string
	var driveParams []string
	var qemuParams []string

	switch object.Type {
	case MemoryBackendFile:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))
		objectParams = append(objectParams, fmt.Sprintf("mem-path=%s", object.MemPath))
		objectParams = append(objectParams, fmt.Sprintf("size=%d", object.Size))

		deviceParams = append(deviceParams, string(object.Driver))
		deviceParams = append(deviceParams, fmt.Sprintf("id=%s", object.DeviceID))
		deviceParams = append(deviceParams, fmt.Sprintf("memdev=%s", object.ID))

		if object.ReadOnly {
			objectParams = append(objectParams, "readonly=on")
			deviceParams = append(deviceParams, "unarmed=on")
		}
	case MemoryBackendEPC:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))
		objectParams = append(objectParams, fmt.Sprintf("size=%d", object.Size))
		if object.Prealloc {
			objectParams = append(objectParams, "prealloc=on")
		}

	case TDXGuest:
		objectParams = append(objectParams, prepareTDXObject(object))
		config.Bios = object.File
	case SEVGuest:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))
		objectParams = append(objectParams, fmt.Sprintf("cbitpos=%d", object.CBitPos))
		objectParams = append(objectParams, fmt.Sprintf("reduced-phys-bits=%d", object.ReducedPhysBits))
		driveParams = append(driveParams, "if=pflash,format=raw,readonly=on")
		driveParams = append(driveParams, fmt.Sprintf("file=%s", object.File))
	case SNPGuest:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))
		objectParams = append(objectParams, fmt.Sprintf("cbitpos=%d", object.CBitPos))
		objectParams = append(objectParams, fmt.Sprintf("reduced-phys-bits=%d", object.ReducedPhysBits))
		objectParams = append(objectParams, "kernel-hashes=on")
		if object.SnpIdBlock != "" {
			objectParams = append(objectParams, fmt.Sprintf("id-block=%s", object.SnpIdBlock))
		}
		if object.SnpIdAuth != "" {
			objectParams = append(objectParams, fmt.Sprintf("id-auth=%s", object.SnpIdAuth))
		}
		config.Bios = object.File
	case SecExecGuest:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))
	case PEFGuest:
		objectParams = append(objectParams, string(object.Type))
		objectParams = append(objectParams, fmt.Sprintf("id=%s", object.ID))

		deviceParams = append(deviceParams, string(object.Driver))
		deviceParams = append(deviceParams, fmt.Sprintf("id=%s", object.DeviceID))
		deviceParams = append(deviceParams, fmt.Sprintf("host-path=%s", object.File))
	}

	if len(deviceParams) > 0 {
		qemuParams = append(qemuParams, "-device")
		qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	}

	if len(objectParams) > 0 {
		qemuParams = append(qemuParams, "-object")
		qemuParams = append(qemuParams, strings.Join(objectParams, ","))
	}

	if len(driveParams) > 0 {
		qemuParams = append(qemuParams, "-drive")
		qemuParams = append(qemuParams, strings.Join(driveParams, ","))
	}

	return qemuParams
}

type SocketAddress struct {
	Type string `json:"type"`
	Cid  string `json:"cid"`
	Port string `json:"port"`
}

type TdxQomObject struct {
	QomType               string        `json:"qom-type"`
	Id                    string        `json:"id"`
	MrConfigId            string        `json:"mrconfigid,omitempty"`
	MrOwner               string        `json:"mrowner,omitempty"`
	MrOwnerConfig         string        `json:"mrownerconfig,omitempty"`
	QuoteGenerationSocket SocketAddress `json:"quote-generation-socket,omitempty"`
	Debug                 *bool         `json:"debug,omitempty"`
}

func (this *SocketAddress) String() string {
	b, err := json.Marshal(*this)

	if err != nil {
		log.Fatalf("Unable to marshal SocketAddress object: %s", err.Error())
		return ""
	}

	return string(b)
}

func (this *TdxQomObject) String() string {
	b, err := json.Marshal(*this)

	if err != nil {
		log.Fatalf("Unable to marshal TDX QOM object: %s", err.Error())
		return ""
	}

	return string(b)
}

func prepareTDXObject(object Object) string {
	qgsSocket := SocketAddress{"vsock", fmt.Sprint(VsockHostCid), fmt.Sprint(object.QgsPort)}
	tdxObject := TdxQomObject{
		string(object.Type), // qom-type
		object.ID,           // id
		"",                  // mrconfigid
		"",                  // mrowner
		"",                  // mrownerconfig
		qgsSocket,           // quote-generation-socket
		nil}

	if object.Debug {
		*tdxObject.Debug = true
	}

	return tdxObject.String()
}

// Virtio9PMultidev filesystem behaviour to deal
// with multiple devices being shared with a 9p export.
type Virtio9PMultidev string

const (
	// Remap shares multiple devices with only one export.
	Remap Virtio9PMultidev = "remap"

	// Warn assumes that only one device is shared by the same export.
	// Only a warning message is logged (once) by qemu on host side.
	// This is the default behaviour.
	Warn Virtio9PMultidev = "warn"

	// Forbid like "warn" but also deny access to additional devices on guest.
	Forbid Virtio9PMultidev = "forbid"
)

// FSDriver represents a qemu filesystem driver.
type FSDriver string

// SecurityModelType is a qemu filesystem security model type.
type SecurityModelType string

const (
	// Local is the local qemu filesystem driver.
	Local FSDriver = "local"

	// Handle is the handle qemu filesystem driver.
	Handle FSDriver = "handle"

	// Proxy is the proxy qemu filesystem driver.
	Proxy FSDriver = "proxy"
)

const (
	// None is like passthrough without failure reports.
	None SecurityModelType = "none"

	// PassThrough uses the same credentials on both the host and guest.
	PassThrough SecurityModelType = "passthrough"

	// MappedXattr stores some files attributes as extended attributes.
	MappedXattr SecurityModelType = "mapped-xattr"

	// MappedFile stores some files attributes in the .virtfs directory.
	MappedFile SecurityModelType = "mapped-file"
)

// FSDevice represents a qemu filesystem configuration.
// nolint: govet
type FSDevice struct {
	// Driver is the qemu device driver
	Driver DeviceDriver

	// FSDriver is the filesystem driver backend.
	FSDriver FSDriver

	// ID is the filesystem identifier.
	ID string

	// Path is the host root path for this filesystem.
	Path string

	// MountTag is the device filesystem mount point tag.
	MountTag string

	// SecurityModel is the security model for this filesystem device.
	SecurityModel SecurityModelType

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport

	// Multidev is the filesystem behaviour to deal
	// with multiple devices being shared with a 9p export
	Multidev Virtio9PMultidev
}

// Virtio9PTransport is a map of the virtio-9p device name that corresponds
// to each transport.
var Virtio9PTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-9p-pci",
	TransportCCW:  "virtio-9p-ccw",
	TransportMMIO: "virtio-9p-device",
}

// Valid returns true if the FSDevice structure is valid and complete.
func (fsdev FSDevice) Valid() bool {
	if fsdev.ID == "" || fsdev.Path == "" || fsdev.MountTag == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this filesystem device.
func (fsdev FSDevice) QemuParams(config *Config) []string {
	var fsParams []string
	var deviceParams []string
	var qemuParams []string

	deviceParams = append(deviceParams, fsdev.deviceName(config))
	if s := fsdev.Transport.disableModern(config, fsdev.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	deviceParams = append(deviceParams, fmt.Sprintf("fsdev=%s", fsdev.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("mount_tag=%s", fsdev.MountTag))
	if fsdev.Transport.isVirtioPCI(config) && fsdev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", fsdev.ROMFile))
	}
	if fsdev.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", fsdev.DevNo))
	}

	fsParams = append(fsParams, string(fsdev.FSDriver))
	fsParams = append(fsParams, fmt.Sprintf("id=%s", fsdev.ID))
	fsParams = append(fsParams, fmt.Sprintf("path=%s", fsdev.Path))
	fsParams = append(fsParams, fmt.Sprintf("security_model=%s", fsdev.SecurityModel))

	if fsdev.Multidev != "" {
		fsParams = append(fsParams, fmt.Sprintf("multidevs=%s", fsdev.Multidev))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	qemuParams = append(qemuParams, "-fsdev")
	qemuParams = append(qemuParams, strings.Join(fsParams, ","))

	return qemuParams
}

// deviceName returns the QEMU shared filesystem device name for the current
// combination of driver and transport.
func (fsdev FSDevice) deviceName(config *Config) string {
	if fsdev.Transport == "" {
		fsdev.Transport = fsdev.Transport.defaultTransport(config)
	}

	switch fsdev.Driver {
	case Virtio9P:
		return Virtio9PTransport[fsdev.Transport]
	}

	return string(fsdev.Driver)
}

// CharDeviceBackend is the character device backend for qemu
type CharDeviceBackend string

const (
	// Pipe creates a 2 way connection to the guest.
	Pipe CharDeviceBackend = "pipe"

	// Socket creates a 2 way stream socket (TCP or Unix).
	Socket CharDeviceBackend = "socket"

	// CharConsole sends traffic from the guest to QEMU's standard output.
	CharConsole CharDeviceBackend = "console"

	// Serial sends traffic from the guest to a serial device on the host.
	Serial CharDeviceBackend = "serial"

	// TTY is an alias for Serial.
	TTY CharDeviceBackend = "tty"

	// PTY creates a new pseudo-terminal on the host and connect to it.
	PTY CharDeviceBackend = "pty"

	// File sends traffic from the guest to a file on the host.
	File CharDeviceBackend = "file"
)

// CharDevice represents a qemu character device.
// nolint: govet
type CharDevice struct {
	Backend CharDeviceBackend

	// Driver is the qemu device driver
	Driver DeviceDriver

	// Bus is the serial bus associated to this device.
	Bus string

	// DeviceID is the user defined device ID.
	DeviceID string

	ID   string
	Path string
	Name string

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// VirtioSerialTransport is a map of the virtio-serial device name that
// corresponds to each transport.
var VirtioSerialTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-serial-pci",
	TransportCCW:  "virtio-serial-ccw",
	TransportMMIO: "virtio-serial-device",
}

// Valid returns true if the CharDevice structure is valid and complete.
func (cdev CharDevice) Valid() bool {
	if cdev.ID == "" || cdev.Path == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this character device.
func (cdev CharDevice) QemuParams(config *Config) []string {
	var cdevParams []string
	var deviceParams []string
	var qemuParams []string

	deviceParams = append(deviceParams, cdev.deviceName(config))
	if cdev.Driver == VirtioSerial {
		if s := cdev.Transport.disableModern(config, cdev.DisableModern); s != "" {
			deviceParams = append(deviceParams, s)
		}
	}
	if cdev.Bus != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", cdev.Bus))
	}
	deviceParams = append(deviceParams, fmt.Sprintf("chardev=%s", cdev.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("id=%s", cdev.DeviceID))
	if cdev.Name != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("name=%s", cdev.Name))
	}
	if cdev.Driver == VirtioSerial && cdev.Transport.isVirtioPCI(config) && cdev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", cdev.ROMFile))
	}

	if cdev.Driver == VirtioSerial && cdev.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", cdev.DevNo))
	}

	cdevParams = append(cdevParams, string(cdev.Backend))
	cdevParams = append(cdevParams, fmt.Sprintf("id=%s", cdev.ID))
	if cdev.Backend == Socket {
		cdevParams = append(cdevParams, fmt.Sprintf("path=%s,server=on,wait=off", cdev.Path))
	} else {
		cdevParams = append(cdevParams, fmt.Sprintf("path=%s", cdev.Path))
	}

	// Legacy serial is special. It does not follow the device + driver model
	if cdev.Driver != LegacySerial {
		qemuParams = append(qemuParams, "-device")
		qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	}

	qemuParams = append(qemuParams, "-chardev")
	qemuParams = append(qemuParams, strings.Join(cdevParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (cdev CharDevice) deviceName(config *Config) string {
	if cdev.Transport == "" {
		cdev.Transport = cdev.Transport.defaultTransport(config)
	}

	switch cdev.Driver {
	case VirtioSerial:
		return VirtioSerialTransport[cdev.Transport]
	}

	return string(cdev.Driver)
}

// NetDeviceType is a qemu networking device type.
type NetDeviceType string

const (
	// TAP is a TAP networking device type.
	TAP NetDeviceType = "tap"

	// MACVTAP is a macvtap networking device type.
	MACVTAP NetDeviceType = "macvtap"

	// IPVTAP is a ipvtap virtual networking device type.
	IPVTAP NetDeviceType = "ipvtap"

	// VETHTAP is a veth-tap virtual networking device type.
	VETHTAP NetDeviceType = "vethtap"

	// VFIO is a direct assigned PCI device or PCI VF
	VFIO NetDeviceType = "VFIO"

	// VHOSTUSER is a vhost-user port (socket)
	VHOSTUSER NetDeviceType = "vhostuser"
)

// QemuNetdevParam converts to the QEMU -netdev parameter notation
func (n NetDeviceType) QemuNetdevParam(netdev *NetDevice, config *Config) string {
	if netdev.Transport == "" {
		netdev.Transport = netdev.Transport.defaultTransport(config)
	}

	switch n {
	case TAP:
		return "tap"
	case MACVTAP:
		return "tap"
	case IPVTAP:
		return "tap"
	case VETHTAP:
		return "tap" // -netdev type=tap -device virtio-net-pci
	case VFIO:
		if netdev.Transport == TransportMMIO {
			log.Fatal("vfio devices are not support with the MMIO transport")
		}
		return "" // -device vfio-pci (no netdev)
	case VHOSTUSER:
		if netdev.Transport == TransportCCW {
			log.Fatal("vhost-user devices are not supported on IBM Z")
		}
		return "vhost-user" // -netdev type=vhost-user (no device)
	default:
		return ""

	}
}

// QemuDeviceParam converts to the QEMU -device parameter notation
func (n NetDeviceType) QemuDeviceParam(netdev *NetDevice, config *Config) DeviceDriver {
	if netdev.Transport == "" {
		netdev.Transport = netdev.Transport.defaultTransport(config)
	}

	var device string

	switch n {
	case TAP:
		device = "virtio-net"
	case MACVTAP:
		device = "virtio-net"
	case IPVTAP:
		device = "virtio-net"
	case VETHTAP:
		device = "virtio-net" // -netdev type=tap -device virtio-net-pci
	case VFIO:
		if netdev.Transport == TransportMMIO {
			log.Fatal("vfio devices are not support with the MMIO transport")
		}
		device = "vfio" // -device vfio-pci (no netdev)
	case VHOSTUSER:
		if netdev.Transport == TransportCCW {
			log.Fatal("vhost-user devices are not supported on IBM Z")
		}
		return "" // -netdev type=vhost-user (no device)
	default:
		return ""
	}

	switch netdev.Transport {
	case TransportPCI:
		return DeviceDriver(device + "-pci")
	case TransportCCW:
		return DeviceDriver(device + "-ccw")
	case TransportMMIO:
		return DeviceDriver(device + "-device")
	default:
		return ""
	}
}

// NetDevice represents a guest networking device
// nolint: govet
type NetDevice struct {
	// Type is the netdev type (e.g. tap).
	Type NetDeviceType

	// Driver is the qemu device driver
	Driver DeviceDriver

	// ID is the netdevice identifier.
	ID string

	// IfName is the interface name,
	IFName string

	// Bus is the bus path name of a PCI device.
	Bus string

	// Addr is the address offset of a PCI device.
	Addr string

	// DownScript is the tap interface deconfiguration script.
	DownScript string

	// Script is the tap interface configuration script.
	Script string

	// FDs represents the list of already existing file descriptors to be used.
	// This is mostly useful for mq support.
	FDs      []*os.File
	VhostFDs []*os.File

	// VHost enables virtio device emulation from the host kernel instead of from qemu.
	VHost bool

	// MACAddress is the networking device interface MAC address.
	MACAddress string

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// VirtioNetTransport is a map of the virtio-net device name that corresponds
// to each transport.
var VirtioNetTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-net-pci",
	TransportCCW:  "virtio-net-ccw",
	TransportMMIO: "virtio-net-device",
}

// Valid returns true if the NetDevice structure is valid and complete.
func (netdev NetDevice) Valid() bool {
	if netdev.ID == "" || netdev.IFName == "" {
		return false
	}

	switch netdev.Type {
	case TAP:
		return true
	case MACVTAP:
		return true
	default:
		return false
	}
}

// mqParameter returns the parameters for multi-queue driver. If the driver is a PCI device then the
// vector flag is required. If the driver is a CCW type than the vector flag is not implemented and only
// multi-queue option mq needs to be activated. See comment in libvirt code at
// https://github.com/libvirt/libvirt/blob/6e7e965dcd3d885739129b1454ce19e819b54c25/src/qemu/qemu_command.c#L3633
func (netdev NetDevice) mqParameter(config *Config) string {
	p := []string{"mq=on"}

	if netdev.Transport.isVirtioPCI(config) {
		// https://www.linux-kvm.org/page/Multiqueue
		// -netdev tap,vhost=on,queues=N
		// enable mq and specify msix vectors in qemu cmdline
		// (2N+2 vectors, N for tx queues, N for rx queues, 1 for config, and one for possible control vq)
		// -device virtio-net-pci,mq=on,vectors=2N+2...
		// enable mq in guest by 'ethtool -L eth0 combined $queue_num'
		// Clearlinux automatically sets up the queues properly
		// The agent implementation should do this to ensure that it is
		// always set
		vectors := len(netdev.FDs)*2 + 2
		p = append(p, fmt.Sprintf("vectors=%d", vectors))
	}

	return strings.Join(p, ",")
}

// QemuDeviceParams returns the -device parameters for this network device
func (netdev NetDevice) QemuDeviceParams(config *Config) []string {
	var deviceParams []string

	driver := netdev.Type.QemuDeviceParam(&netdev, config)
	if driver == "" {
		return nil
	}

	deviceParams = append(deviceParams, fmt.Sprintf("driver=%s", driver))
	deviceParams = append(deviceParams, fmt.Sprintf("netdev=%s", netdev.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("mac=%s", netdev.MACAddress))

	if netdev.Bus != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", netdev.Bus))
	}

	if netdev.Addr != "" {
		addr, err := strconv.Atoi(netdev.Addr)
		if err == nil && addr >= 0 {
			deviceParams = append(deviceParams, fmt.Sprintf("addr=%x", addr))
		}
	}
	if s := netdev.Transport.disableModern(config, netdev.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}

	if len(netdev.FDs) > 0 {
		// Note: We are appending to the device params here
		deviceParams = append(deviceParams, netdev.mqParameter(config))
	}

	if netdev.Transport.isVirtioPCI(config) && netdev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", netdev.ROMFile))
	}

	if netdev.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", netdev.DevNo))
	}

	return deviceParams
}

// QemuNetdevParams returns the -netdev parameters for this network device
func (netdev NetDevice) QemuNetdevParams(config *Config) []string {
	var netdevParams []string

	netdevType := netdev.Type.QemuNetdevParam(&netdev, config)
	if netdevType == "" {
		return nil
	}

	netdevParams = append(netdevParams, netdevType)
	netdevParams = append(netdevParams, fmt.Sprintf("id=%s", netdev.ID))

	if netdev.VHost {
		netdevParams = append(netdevParams, "vhost=on")
		if len(netdev.VhostFDs) > 0 {
			var fdParams []string
			qemuFDs := config.appendFDs(netdev.VhostFDs)
			for _, fd := range qemuFDs {
				fdParams = append(fdParams, fmt.Sprintf("%d", fd))
			}
			netdevParams = append(netdevParams, fmt.Sprintf("vhostfds=%s", strings.Join(fdParams, ":")))
		}
	}

	if len(netdev.FDs) > 0 {
		var fdParams []string

		qemuFDs := config.appendFDs(netdev.FDs)
		for _, fd := range qemuFDs {
			fdParams = append(fdParams, fmt.Sprintf("%d", fd))
		}

		netdevParams = append(netdevParams, fmt.Sprintf("fds=%s", strings.Join(fdParams, ":")))

	} else {
		netdevParams = append(netdevParams, fmt.Sprintf("ifname=%s", netdev.IFName))
		if netdev.DownScript != "" {
			netdevParams = append(netdevParams, fmt.Sprintf("downscript=%s", netdev.DownScript))
		}
		if netdev.Script != "" {
			netdevParams = append(netdevParams, fmt.Sprintf("script=%s", netdev.Script))
		}
	}
	return netdevParams
}

// QemuParams returns the qemu parameters built out of this network device.
func (netdev NetDevice) QemuParams(config *Config) []string {
	var netdevParams []string
	var deviceParams []string
	var qemuParams []string

	// Macvtap can only be connected via fds
	if (netdev.Type == MACVTAP) && (len(netdev.FDs) == 0) {
		return nil // implicit error
	}

	if netdev.Type.QemuNetdevParam(&netdev, config) != "" {
		netdevParams = netdev.QemuNetdevParams(config)
		if netdevParams != nil {
			qemuParams = append(qemuParams, "-netdev")
			qemuParams = append(qemuParams, strings.Join(netdevParams, ","))
		}
	}

	if netdev.Type.QemuDeviceParam(&netdev, config) != "" {
		deviceParams = netdev.QemuDeviceParams(config)
		if deviceParams != nil {
			qemuParams = append(qemuParams, "-device")
			qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
		}
	}

	return qemuParams
}

// LegacySerialDevice represents a qemu legacy serial device.
type LegacySerialDevice struct {
	// ID is the serial device identifier.
	// This maps to the char dev associated with the device
	// as serial does not have a notion of id
	// e.g:
	// -chardev stdio,id=char0,mux=on,logfile=serial.log,signal=off -serial chardev:char0
	// -chardev file,id=char0,path=serial.log -serial chardev:char0
	Chardev string
}

// Valid returns true if the LegacySerialDevice structure is valid and complete.
func (dev LegacySerialDevice) Valid() bool {
	return dev.Chardev != ""
}

// QemuParams returns the qemu parameters built out of this serial device.
func (dev LegacySerialDevice) QemuParams(config *Config) []string {
	var deviceParam string
	var qemuParams []string

	deviceParam = fmt.Sprintf("chardev:%s", dev.Chardev)

	qemuParams = append(qemuParams, "-serial")
	qemuParams = append(qemuParams, deviceParam)

	return qemuParams
}

/* Not used currently
// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (dev LegacySerialDevice) deviceName(config *Config) string {
	return dev.Chardev
}
*/

// SerialDevice represents a qemu serial device.
// nolint: govet
type SerialDevice struct {
	// Driver is the qemu device driver
	Driver DeviceDriver

	// ID is the serial device identifier.
	ID string

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport

	// MaxPorts is the maximum number of ports for this device.
	MaxPorts uint
}

// Valid returns true if the SerialDevice structure is valid and complete.
func (dev SerialDevice) Valid() bool {
	if dev.Driver == "" || dev.ID == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this serial device.
func (dev SerialDevice) QemuParams(config *Config) []string {
	var deviceParams []string
	var qemuParams []string

	deviceParams = append(deviceParams, dev.deviceName(config))
	if s := dev.Transport.disableModern(config, dev.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	deviceParams = append(deviceParams, fmt.Sprintf("id=%s", dev.ID))
	if dev.Transport.isVirtioPCI(config) && dev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", dev.ROMFile))
		if dev.Driver == VirtioSerial && dev.MaxPorts != 0 {
			deviceParams = append(deviceParams, fmt.Sprintf("max_ports=%d", dev.MaxPorts))
		}
	}

	if dev.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", dev.DevNo))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (dev SerialDevice) deviceName(config *Config) string {
	if dev.Transport == "" {
		dev.Transport = dev.Transport.defaultTransport(config)
	}

	switch dev.Driver {
	case VirtioSerial:
		return VirtioSerialTransport[dev.Transport]
	}

	return string(dev.Driver)
}

// BlockDeviceInterface defines the type of interface the device is connected to.
type BlockDeviceInterface string

// BlockDeviceAIO defines the type of asynchronous I/O the block device should use.
type BlockDeviceAIO string

// BlockDeviceFormat defines the image format used on a block device.
type BlockDeviceFormat string

const (
	// NoInterface for block devices with no interfaces.
	NoInterface BlockDeviceInterface = "none"

	// SCSI represents a SCSI block device interface.
	SCSI BlockDeviceInterface = "scsi"
)

const (
	// Threads is the pthread asynchronous I/O implementation.
	Threads BlockDeviceAIO = "threads"

	// Native is the native Linux AIO implementation.
	Native BlockDeviceAIO = "native"

	// IOUring is the Linux io_uring I/O implementation.
	IOUring BlockDeviceAIO = "io_uring"
)

const (
	// QCOW2 is the Qemu Copy On Write v2 image format.
	QCOW2 BlockDeviceFormat = "qcow2"
)

// BlockDevice represents a qemu block device.
// nolint: govet
type BlockDevice struct {
	Driver    DeviceDriver
	ID        string
	File      string
	Interface BlockDeviceInterface
	AIO       BlockDeviceAIO
	Format    BlockDeviceFormat
	SCSI      bool
	WCE       bool

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// ShareRW enables multiple qemu instances to share the File
	ShareRW bool

	// ReadOnly sets the block device in readonly mode
	ReadOnly bool

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// VirtioBlockTransport is a map of the virtio-blk device name that corresponds
// to each transport.
var VirtioBlockTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-blk-pci",
	TransportCCW:  "virtio-blk-ccw",
	TransportMMIO: "virtio-blk-device",
}

// Valid returns true if the BlockDevice structure is valid and complete.
func (blkdev BlockDevice) Valid() bool {
	if blkdev.Driver == "" || blkdev.ID == "" || blkdev.File == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this block device.
func (blkdev BlockDevice) QemuParams(config *Config) []string {
	var blkParams []string
	var deviceParams []string
	var qemuParams []string

	deviceParams = append(deviceParams, blkdev.deviceName(config))
	if s := blkdev.Transport.disableModern(config, blkdev.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	deviceParams = append(deviceParams, fmt.Sprintf("drive=%s", blkdev.ID))
	if !blkdev.WCE {
		deviceParams = append(deviceParams, "config-wce=off")
	}

	if blkdev.Transport.isVirtioPCI(config) && blkdev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", blkdev.ROMFile))
	}

	if blkdev.Transport.isVirtioCCW(config) {
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", blkdev.DevNo))
	}

	if blkdev.ShareRW {
		deviceParams = append(deviceParams, "share-rw=on")
	}

	deviceParams = append(deviceParams, fmt.Sprintf("serial=%s", blkdev.ID))

	blkParams = append(blkParams, fmt.Sprintf("id=%s", blkdev.ID))
	blkParams = append(blkParams, fmt.Sprintf("file=%s", blkdev.File))
	blkParams = append(blkParams, fmt.Sprintf("aio=%s", blkdev.AIO))
	blkParams = append(blkParams, fmt.Sprintf("format=%s", blkdev.Format))
	blkParams = append(blkParams, fmt.Sprintf("if=%s", blkdev.Interface))

	if blkdev.ReadOnly {
		blkParams = append(blkParams, "readonly=on")
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	qemuParams = append(qemuParams, "-drive")
	qemuParams = append(qemuParams, strings.Join(blkParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (blkdev BlockDevice) deviceName(config *Config) string {
	if blkdev.Transport == "" {
		blkdev.Transport = blkdev.Transport.defaultTransport(config)
	}

	switch blkdev.Driver {
	case VirtioBlock:
		return VirtioBlockTransport[blkdev.Transport]
	}

	return string(blkdev.Driver)
}

// PVPanicDevice represents a qemu pvpanic device.
type PVPanicDevice struct {
	NoShutdown bool
}

// Valid always returns true for pvpanic device
func (dev PVPanicDevice) Valid() bool {
	return true
}

// QemuParams returns the qemu parameters built out of this serial device.
func (dev PVPanicDevice) QemuParams(config *Config) []string {
	if dev.NoShutdown {
		return []string{"-device", "pvpanic", "-no-shutdown"}
	}
	return []string{"-device", "pvpanic"}
}

// LoaderDevice represents a qemu loader device.
type LoaderDevice struct {
	File string
	ID   string
}

// Valid returns true if there is a valid structure defined for LoaderDevice
func (dev LoaderDevice) Valid() bool {
	if dev.File == "" {
		return false
	}

	if dev.ID == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this loader device.
func (dev LoaderDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	deviceParams = append(deviceParams, "loader")
	deviceParams = append(deviceParams, fmt.Sprintf("file=%s", dev.File))
	deviceParams = append(deviceParams, fmt.Sprintf("id=%s", dev.ID))

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// VhostUserDevice represents a qemu vhost-user device meant to be passed
// in to the guest
// nolint: govet
type VhostUserDevice struct {
	SocketPath    string //path to vhostuser socket on host
	CharDevID     string
	TypeDevID     string //variable QEMU parameter based on value of VhostUserType
	Address       string //used for MAC address in net case
	Tag           string //virtio-fs volume id for mounting inside guest
	CacheSize     uint32 //virtio-fs DAX cache size in MiB
	QueueSize     uint32 //size of virtqueues
	VhostUserType DeviceDriver

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the CCW device for s390x.
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// VhostUserNetTransport is a map of the virtio-net device name that
// corresponds to each transport.
var VhostUserNetTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-net-pci",
	TransportCCW:  "virtio-net-ccw",
	TransportMMIO: "virtio-net-device",
}

// VhostUserSCSITransport is a map of the vhost-user-scsi device name that
// corresponds to each transport.
var VhostUserSCSITransport = map[VirtioTransport]string{
	TransportPCI:  "vhost-user-scsi-pci",
	TransportCCW:  "vhost-user-scsi-ccw",
	TransportMMIO: "vhost-user-scsi-device",
}

// VhostUserBlkTransport is a map of the vhost-user-blk device name that
// corresponds to each transport.
var VhostUserBlkTransport = map[VirtioTransport]string{
	TransportPCI:  "vhost-user-blk-pci",
	TransportCCW:  "vhost-user-blk-ccw",
	TransportMMIO: "vhost-user-blk-device",
}

// VhostUserFSTransport is a map of the vhost-user-fs device name that
// corresponds to each transport.
var VhostUserFSTransport = map[VirtioTransport]string{
	TransportPCI:  "vhost-user-fs-pci",
	TransportCCW:  "vhost-user-fs-ccw",
	TransportMMIO: "vhost-user-fs-device",
}

// Valid returns true if there is a valid structure defined for VhostUserDevice
func (vhostuserDev VhostUserDevice) Valid() bool {

	if vhostuserDev.SocketPath == "" || vhostuserDev.CharDevID == "" {
		return false
	}

	switch vhostuserDev.VhostUserType {
	case VhostUserNet:
		if vhostuserDev.TypeDevID == "" || vhostuserDev.Address == "" {
			return false
		}
	case VhostUserSCSI:
		if vhostuserDev.TypeDevID == "" {
			return false
		}
	case VhostUserBlk:
	case VhostUserFS:
		if vhostuserDev.Tag == "" {
			return false
		}
	default:
		return false
	}

	return true
}

// QemuNetParams builds QEMU netdev and device parameters for a VhostUserNet device
func (vhostuserDev VhostUserDevice) QemuNetParams(config *Config) []string {
	var qemuParams []string
	var netParams []string
	var deviceParams []string

	driver := vhostuserDev.deviceName(config)
	if driver == "" {
		return nil
	}

	netParams = append(netParams, "type=vhost-user")
	netParams = append(netParams, fmt.Sprintf("id=%s", vhostuserDev.TypeDevID))
	netParams = append(netParams, fmt.Sprintf("chardev=%s", vhostuserDev.CharDevID))
	netParams = append(netParams, "vhostforce")

	deviceParams = append(deviceParams, driver)
	deviceParams = append(deviceParams, fmt.Sprintf("netdev=%s", vhostuserDev.TypeDevID))
	deviceParams = append(deviceParams, fmt.Sprintf("mac=%s", vhostuserDev.Address))

	if vhostuserDev.Transport.isVirtioPCI(config) && vhostuserDev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vhostuserDev.ROMFile))
	}

	qemuParams = append(qemuParams, "-netdev")
	qemuParams = append(qemuParams, strings.Join(netParams, ","))
	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// QemuSCSIParams builds QEMU device parameters for a VhostUserSCSI device
func (vhostuserDev VhostUserDevice) QemuSCSIParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := vhostuserDev.deviceName(config)
	if driver == "" {
		return nil
	}

	deviceParams = append(deviceParams, driver)
	deviceParams = append(deviceParams, fmt.Sprintf("id=%s", vhostuserDev.TypeDevID))
	deviceParams = append(deviceParams, fmt.Sprintf("chardev=%s", vhostuserDev.CharDevID))

	if vhostuserDev.Transport.isVirtioPCI(config) && vhostuserDev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vhostuserDev.ROMFile))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// QemuBlkParams builds QEMU device parameters for a VhostUserBlk device
func (vhostuserDev VhostUserDevice) QemuBlkParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := vhostuserDev.deviceName(config)
	if driver == "" {
		return nil
	}

	deviceParams = append(deviceParams, driver)
	deviceParams = append(deviceParams, "logical_block_size=4096")
	deviceParams = append(deviceParams, "size=512M")
	deviceParams = append(deviceParams, fmt.Sprintf("chardev=%s", vhostuserDev.CharDevID))

	if vhostuserDev.Transport.isVirtioPCI(config) && vhostuserDev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vhostuserDev.ROMFile))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// QemuFSParams builds QEMU device parameters for a VhostUserFS device
func (vhostuserDev VhostUserDevice) QemuFSParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := vhostuserDev.deviceName(config)
	if driver == "" {
		return nil
	}

	deviceParams = append(deviceParams, driver)
	deviceParams = append(deviceParams, fmt.Sprintf("chardev=%s", vhostuserDev.CharDevID))
	deviceParams = append(deviceParams, fmt.Sprintf("tag=%s", vhostuserDev.Tag))
	queueSize := uint32(1024)
	if vhostuserDev.QueueSize != 0 {
		queueSize = vhostuserDev.QueueSize
	}
	deviceParams = append(deviceParams, fmt.Sprintf("queue-size=%d", queueSize))
	if vhostuserDev.CacheSize != 0 {
		deviceParams = append(deviceParams, fmt.Sprintf("cache-size=%dM", vhostuserDev.CacheSize))
	}
	if vhostuserDev.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", vhostuserDev.DevNo))
	}
	if vhostuserDev.Transport.isVirtioPCI(config) && vhostuserDev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vhostuserDev.ROMFile))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// QemuParams returns the qemu parameters built out of this vhostuser device.
func (vhostuserDev VhostUserDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var charParams []string
	var deviceParams []string

	charParams = append(charParams, "socket")
	charParams = append(charParams, fmt.Sprintf("id=%s", vhostuserDev.CharDevID))
	charParams = append(charParams, fmt.Sprintf("path=%s", vhostuserDev.SocketPath))

	qemuParams = append(qemuParams, "-chardev")
	qemuParams = append(qemuParams, strings.Join(charParams, ","))

	switch vhostuserDev.VhostUserType {
	case VhostUserNet:
		deviceParams = vhostuserDev.QemuNetParams(config)
	case VhostUserSCSI:
		deviceParams = vhostuserDev.QemuSCSIParams(config)
	case VhostUserBlk:
		deviceParams = vhostuserDev.QemuBlkParams(config)
	case VhostUserFS:
		deviceParams = vhostuserDev.QemuFSParams(config)
	default:
		return nil
	}

	if deviceParams != nil {
		return append(qemuParams, deviceParams...)
	}

	return nil
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (vhostuserDev VhostUserDevice) deviceName(config *Config) string {
	if vhostuserDev.Transport == "" {
		vhostuserDev.Transport = vhostuserDev.Transport.defaultTransport(config)
	}

	switch vhostuserDev.VhostUserType {
	case VhostUserNet:
		return VhostUserNetTransport[vhostuserDev.Transport]
	case VhostUserSCSI:
		return VhostUserSCSITransport[vhostuserDev.Transport]
	case VhostUserBlk:
		return VhostUserBlkTransport[vhostuserDev.Transport]
	case VhostUserFS:
		return VhostUserFSTransport[vhostuserDev.Transport]
	default:
		return ""
	}
}

// PCIeRootPortDevice represents a memory balloon device.
// nolint: govet
type PCIeRootPortDevice struct {
	ID string // format: rp{n}, n>=0

	Bus     string // default is pcie.0
	Chassis string // (slot, chassis) pair is mandatory and must be unique for each pcie-root-port, >=0, default is 0x00
	Slot    string // >=0, default is 0x00

	Multifunction bool   // true => "on", false => "off", default is off
	Addr          string // >=0, default is 0x00

	// The PCIE-PCI bridge can be hot-plugged only into pcie-root-port that has 'bus-reserve' property value to
	// provide secondary bus for the hot-plugged bridge.
	BusReserve    string
	Pref64Reserve string // reserve prefetched MMIO aperture, 64-bit
	Pref32Reserve string // reserve prefetched MMIO aperture, 32-bit
	MemReserve    string // reserve non-prefetched MMIO aperture, 32-bit *only*
	IOReserve     string // IO reservation

	ROMFile string // ROMFile specifies the ROM file being used for this device.

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// QemuParams returns the qemu parameters built out of the PCIeRootPortDevice.
func (b PCIeRootPortDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string
	driver := PCIeRootPort

	deviceParams = append(deviceParams, fmt.Sprintf("%s,id=%s", driver, b.ID))

	if b.Bus == "" {
		b.Bus = "pcie.0"
	}
	deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", b.Bus))

	if b.Chassis == "" {
		b.Chassis = "0x00"
	}
	deviceParams = append(deviceParams, fmt.Sprintf("chassis=%s", b.Chassis))

	if b.Slot == "" {
		b.Slot = "0x00"
	}
	deviceParams = append(deviceParams, fmt.Sprintf("slot=%s", b.Slot))

	multifunction := "off"
	if b.Multifunction {
		multifunction = "on"
		if b.Addr == "" {
			b.Addr = "0x00"
		}
		deviceParams = append(deviceParams, fmt.Sprintf("addr=%s", b.Addr))
	}
	deviceParams = append(deviceParams, fmt.Sprintf("multifunction=%v", multifunction))

	if b.BusReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus-reserve=%s", b.BusReserve))
	}

	if b.Pref64Reserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("pref64-reserve=%s", b.Pref64Reserve))
	}

	if b.Pref32Reserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("pref32-reserve=%s", b.Pref32Reserve))
	}

	if b.MemReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("mem-reserve=%s", b.MemReserve))
	}

	if b.IOReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("io-reserve=%s", b.IOReserve))
	}

	if b.Transport.isVirtioPCI(config) && b.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", b.ROMFile))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	return qemuParams
}

// Valid returns true if the PCIeRootPortDevice structure is valid and complete.
func (b PCIeRootPortDevice) Valid() bool {
	// the "pref32-reserve" and "pref64-reserve" hints are mutually exclusive.
	if b.Pref64Reserve != "" && b.Pref32Reserve != "" {
		return false
	}
	if b.ID == "" {
		return false
	}
	return true
}

// PCIeSwitchUpstreamPortDevice is the port connecting to the root port
type PCIeSwitchUpstreamPortDevice struct {
	ID  string // format: sup{n}, n>=0
	Bus string // default is rp0
}

// QemuParams returns the qemu parameters built out of the PCIeSwitchUpstreamPortDevice.
func (b PCIeSwitchUpstreamPortDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := PCIeSwitchUpstreamPort

	deviceParams = append(deviceParams, fmt.Sprintf("%s,id=%s", driver, b.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", b.Bus))

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	return qemuParams
}

// Valid returns true if the PCIeSwitchUpstreamPortDevice structure is valid and complete.
func (b PCIeSwitchUpstreamPortDevice) Valid() bool {
	if b.ID == "" {
		return false
	}
	if b.Bus == "" {
		return false
	}
	return true
}

// PCIeSwitchDownstreamPortDevice is the port connecting to the root port
type PCIeSwitchDownstreamPortDevice struct {
	ID      string // format: sup{n}, n>=0
	Bus     string // default is rp0
	Chassis string // (slot, chassis) pair is mandatory and must be unique for each downstream port, >=0, default is 0x00
	Slot    string // >=0, default is 0x00
	// This to work needs patches to QEMU
	BusReserve string
	// Pref64 and Pref32 are not allowed to be set simultaneously
	Pref64Reserve string // reserve prefetched MMIO aperture, 64-bit
	Pref32Reserve string // reserve prefetched MMIO aperture, 32-bit
	MemReserve    string // reserve non-prefetched MMIO aperture, 32-bit *only*
	IOReserve     string // IO reservation

}

// QemuParams returns the qemu parameters built out of the PCIeSwitchUpstreamPortDevice.
func (b PCIeSwitchDownstreamPortDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string
	driver := PCIeSwitchDownstreamPort

	deviceParams = append(deviceParams, fmt.Sprintf("%s,id=%s", driver, b.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", b.Bus))
	deviceParams = append(deviceParams, fmt.Sprintf("chassis=%s", b.Chassis))
	deviceParams = append(deviceParams, fmt.Sprintf("slot=%s", b.Slot))
	if b.BusReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus-reserve=%s", b.BusReserve))
	}

	if b.Pref64Reserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("pref64-reserve=%s", b.Pref64Reserve))
	}

	if b.Pref32Reserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("pref32-reserve=%s", b.Pref32Reserve))
	}

	if b.MemReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("mem-reserve=%s", b.MemReserve))
	}

	if b.IOReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("io-reserve=%s", b.IOReserve))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	return qemuParams
}

// Valid returns true if the PCIeSwitchUpstremPortDevice structure is valid and complete.
func (b PCIeSwitchDownstreamPortDevice) Valid() bool {
	if b.ID == "" {
		return false
	}
	if b.Bus == "" {
		return false
	}
	if b.Chassis == "" {
		return false
	}
	if b.Slot == "" {
		return false
	}
	return true
}

// VFIODevice represents a qemu vfio device meant for direct access by guest OS.
type VFIODevice struct {
	// ID index of the vfio device in devfs or sysfs used for IOMMUFD
	ID string

	// Bus-Device-Function of device
	BDF string

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// VendorID specifies vendor id
	VendorID string

	// DeviceID specifies device id
	DeviceID string

	// Bus specifies device bus
	Bus string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport

	// SysfsDev specifies the sysfs matrix entry for the AP device
	SysfsDev string

	// DevfsDev is used to identify a VFIO Group device or IOMMMUFD VFIO device
	DevfsDev string
}

// VFIODeviceTransport is a map of the vfio device name that corresponds to
// each transport.
var VFIODeviceTransport = map[VirtioTransport]string{
	TransportPCI:  "vfio-pci",
	TransportCCW:  "vfio-ccw",
	TransportMMIO: "vfio-device",
	TransportAP:   "vfio-ap",
}

// Valid returns true if the VFIODevice structure is valid and complete.
// s390x architecture requires SysfsDev to be set.
func (vfioDev VFIODevice) Valid() bool {
	return vfioDev.BDF != "" || vfioDev.SysfsDev != ""
}

// QemuParams returns the qemu parameters built out of this vfio device.
func (vfioDev VFIODevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := vfioDev.deviceName(config)

	if vfioDev.Transport.isVirtioAP(config) {
		deviceParams = append(deviceParams, fmt.Sprintf("%s,sysfsdev=%s", driver, vfioDev.SysfsDev))

		qemuParams = append(qemuParams, "-device")
		qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

		return qemuParams
	}

	deviceParams = append(deviceParams, fmt.Sprintf("%s,host=%s", driver, vfioDev.BDF))
	if vfioDev.Transport.isVirtioPCI(config) {
		if vfioDev.VendorID != "" {
			deviceParams = append(deviceParams, fmt.Sprintf("x-pci-vendor-id=%s", vfioDev.VendorID))
		}
		if vfioDev.DeviceID != "" {
			deviceParams = append(deviceParams, fmt.Sprintf("x-pci-device-id=%s", vfioDev.DeviceID))
		}
		if vfioDev.ROMFile != "" {
			deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vfioDev.ROMFile))
		}
	}

	if vfioDev.Bus != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", vfioDev.Bus))
	}

	if vfioDev.Transport.isVirtioCCW(config) {
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", vfioDev.DevNo))
	}

	if strings.HasPrefix(vfioDev.DevfsDev, drivers.IommufdDevPath) {
		qemuParams = append(qemuParams, "-object")
		qemuParams = append(qemuParams, fmt.Sprintf("iommufd,id=iommufd%s", vfioDev.ID))
		deviceParams = append(deviceParams, fmt.Sprintf("iommufd=iommufd%s", vfioDev.ID))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (vfioDev VFIODevice) deviceName(config *Config) string {
	if vfioDev.Transport == "" {
		vfioDev.Transport = vfioDev.Transport.defaultTransport(config)
	}

	return VFIODeviceTransport[vfioDev.Transport]
}

// SCSIController represents a SCSI controller device.
// nolint: govet
type SCSIController struct {
	ID string

	// Bus on which the SCSI controller is attached, this is optional
	Bus string

	// Addr is the PCI address offset, this is optional
	Addr string

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// IOThread is the IO thread on which IO will be handled
	IOThread string

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// SCSIControllerTransport is a map of the virtio-scsi device name that
// corresponds to each transport.
var SCSIControllerTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-scsi-pci",
	TransportCCW:  "virtio-scsi-ccw",
	TransportMMIO: "virtio-scsi-device",
}

// Valid returns true if the SCSIController structure is valid and complete.
func (scsiCon SCSIController) Valid() bool {
	return scsiCon.ID != ""
}

// QemuParams returns the qemu parameters built out of this SCSIController device.
func (scsiCon SCSIController) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	driver := scsiCon.deviceName(config)
	deviceParams = append(deviceParams, fmt.Sprintf("%s,id=%s", driver, scsiCon.ID))
	if scsiCon.Bus != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("bus=%s", scsiCon.Bus))
	}
	if scsiCon.Addr != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("addr=%s", scsiCon.Addr))
	}
	if s := scsiCon.Transport.disableModern(config, scsiCon.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	if scsiCon.IOThread != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("iothread=%s", scsiCon.IOThread))
	}
	if scsiCon.Transport.isVirtioPCI(config) && scsiCon.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", scsiCon.ROMFile))
	}

	if scsiCon.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", scsiCon.DevNo))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (scsiCon SCSIController) deviceName(config *Config) string {
	if scsiCon.Transport == "" {
		scsiCon.Transport = scsiCon.Transport.defaultTransport(config)
	}

	return SCSIControllerTransport[scsiCon.Transport]
}

// BridgeType is the type of the bridge
type BridgeType uint

const (
	// PCIBridge is a pci bridge
	PCIBridge BridgeType = iota

	// PCIEBridge is a pcie bridge
	PCIEBridge
)

// BridgeDevice represents a qemu bridge device like pci-bridge, pxb, etc.
// nolint: govet
type BridgeDevice struct {
	// Type of the bridge
	Type BridgeType

	// Bus number where the bridge is plugged, typically pci.0 or pcie.0
	Bus string

	// ID is used to identify the bridge in qemu
	ID string

	// Chassis number
	Chassis int

	// SHPC is used to enable or disable the standard hot plug controller
	SHPC bool

	// PCI Slot
	Addr string

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// Address range reservations for devices behind the bridge
	// NB: strings seem an odd choice, but if they were integers,
	// they'd default to 0 by Go's rules in all the existing users
	// who don't set them.  0 is a valid value for certain cases,
	// but not you want by default.
	IOReserve     string
	MemReserve    string
	Pref64Reserve string
}

// Valid returns true if the BridgeDevice structure is valid and complete.
func (bridgeDev BridgeDevice) Valid() bool {
	if bridgeDev.Type != PCIBridge && bridgeDev.Type != PCIEBridge {
		return false
	}

	if bridgeDev.Bus == "" {
		return false
	}

	if bridgeDev.ID == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of this bridge device.
func (bridgeDev BridgeDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string
	var driver DeviceDriver

	switch bridgeDev.Type {
	case PCIEBridge:
		driver = PCIePCIBridgeDriver
		deviceParams = append(deviceParams, fmt.Sprintf("%s,bus=%s,id=%s", driver, bridgeDev.Bus, bridgeDev.ID))
	default:
		driver = PCIBridgeDriver
		shpc := "off"
		if bridgeDev.SHPC {
			shpc = "on"
		}
		deviceParams = append(deviceParams, fmt.Sprintf("%s,bus=%s,id=%s,chassis_nr=%d,shpc=%s", driver, bridgeDev.Bus, bridgeDev.ID, bridgeDev.Chassis, shpc))
	}

	if bridgeDev.Addr != "" {
		addr, err := strconv.Atoi(bridgeDev.Addr)
		if err == nil && addr >= 0 {
			deviceParams = append(deviceParams, fmt.Sprintf("addr=%x", addr))
		}
	}

	var transport VirtioTransport
	if transport.isVirtioPCI(config) && bridgeDev.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", bridgeDev.ROMFile))
	}

	if bridgeDev.IOReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("io-reserve=%s", bridgeDev.IOReserve))
	}
	if bridgeDev.MemReserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("mem-reserve=%s", bridgeDev.MemReserve))
	}
	if bridgeDev.Pref64Reserve != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("pref64-reserve=%s", bridgeDev.Pref64Reserve))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// VSOCKDevice represents a AF_VSOCK socket.
// nolint: govet
type VSOCKDevice struct {
	ID string

	ContextID uint64

	// VHostFD vhost file descriptor that holds the ContextID
	VHostFD *os.File

	// DisableModern prevents qemu from relying on fast MMIO.
	DisableModern bool

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// VSOCKDeviceTransport is a map of the vhost-vsock device name that
// corresponds to each transport.
var VSOCKDeviceTransport = map[VirtioTransport]string{
	TransportPCI:  "vhost-vsock-pci",
	TransportCCW:  "vhost-vsock-ccw",
	TransportMMIO: "vhost-vsock-device",
}

const (
	// MinimalGuestCID is the smallest valid context ID for a guest.
	MinimalGuestCID uint64 = 3

	// MaxGuestCID is the largest valid context ID for a guest.
	MaxGuestCID uint64 = 1<<32 - 1
)

const (
	// VSOCKGuestCID is the VSOCK guest CID parameter.
	VSOCKGuestCID = "guest-cid"
)

// Valid returns true if the VSOCKDevice structure is valid and complete.
func (vsock VSOCKDevice) Valid() bool {
	if vsock.ID == "" || vsock.ContextID < MinimalGuestCID || vsock.ContextID > MaxGuestCID {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of the VSOCK device.
func (vsock VSOCKDevice) QemuParams(config *Config) []string {
	var deviceParams []string
	var qemuParams []string

	driver := vsock.deviceName(config)
	deviceParams = append(deviceParams, driver)
	if s := vsock.Transport.disableModern(config, vsock.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	if vsock.VHostFD != nil {
		qemuFDs := config.appendFDs([]*os.File{vsock.VHostFD})
		deviceParams = append(deviceParams, fmt.Sprintf("vhostfd=%d", qemuFDs[0]))
	}
	deviceParams = append(deviceParams, fmt.Sprintf("id=%s", vsock.ID))
	deviceParams = append(deviceParams, fmt.Sprintf("%s=%d", VSOCKGuestCID, vsock.ContextID))

	if vsock.Transport.isVirtioPCI(config) && vsock.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", vsock.ROMFile))
	}

	if vsock.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", vsock.DevNo))
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (vsock VSOCKDevice) deviceName(config *Config) string {
	if vsock.Transport == "" {
		vsock.Transport = vsock.Transport.defaultTransport(config)
	}

	return VSOCKDeviceTransport[vsock.Transport]
}

// RngDevice represents a random number generator device.
// nolint: govet
type RngDevice struct {
	// ID is the device ID
	ID string
	// Filename is entropy source on the host
	Filename string
	// MaxBytes is the bytes allowed to guest to get from the hosts entropy per period
	MaxBytes uint
	// Period is duration of a read period in seconds
	Period uint
	// ROMFile specifies the ROM file being used for this device.
	ROMFile string
	// DevNo identifies the ccw devices for s390x architecture
	DevNo string
	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// RngDeviceTransport is a map of the virtio-rng device name that corresponds
// to each transport.
var RngDeviceTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-rng-pci",
	TransportCCW:  "virtio-rng-ccw",
	TransportMMIO: "virtio-rng-device",
}

// Valid returns true if the RngDevice structure is valid and complete.
func (v RngDevice) Valid() bool {
	return v.ID != ""
}

// QemuParams returns the qemu parameters built out of the RngDevice.
func (v RngDevice) QemuParams(config *Config) []string {
	var qemuParams []string

	//-object rng-random,filename=/dev/hwrng,id=rng0
	var objectParams []string
	//-device virtio-rng-pci,rng=rng0,max-bytes=1024,period=1000
	var deviceParams []string

	objectParams = append(objectParams, "rng-random")
	objectParams = append(objectParams, "id="+v.ID)

	deviceParams = append(deviceParams, v.deviceName(config))
	deviceParams = append(deviceParams, "rng="+v.ID)

	if v.Transport.isVirtioPCI(config) && v.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", v.ROMFile))
	}

	if v.Transport.isVirtioCCW(config) {
		if config.Knobs.IOMMUPlatform {
			deviceParams = append(deviceParams, "iommu_platform=on")
		}
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", v.DevNo))
	}

	if v.Filename != "" {
		objectParams = append(objectParams, "filename="+v.Filename)
	}

	if v.MaxBytes > 0 {
		deviceParams = append(deviceParams, fmt.Sprintf("max-bytes=%d", v.MaxBytes))
	}

	if v.Period > 0 {
		deviceParams = append(deviceParams, fmt.Sprintf("period=%d", v.Period))
	}

	qemuParams = append(qemuParams, "-object")
	qemuParams = append(qemuParams, strings.Join(objectParams, ","))

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (v RngDevice) deviceName(config *Config) string {
	if v.Transport == "" {
		v.Transport = v.Transport.defaultTransport(config)
	}

	return RngDeviceTransport[v.Transport]
}

// BalloonDevice represents a memory balloon device.
// nolint: govet
type BalloonDevice struct {
	DeflateOnOOM  bool
	DisableModern bool
	ID            string

	// ROMFile specifies the ROM file being used for this device.
	ROMFile string

	// DevNo identifies the ccw devices for s390x architecture
	DevNo string

	// Transport is the virtio transport for this device.
	Transport VirtioTransport
}

// BalloonDeviceTransport is a map of the virtio-balloon device name that
// corresponds to each transport.
var BalloonDeviceTransport = map[VirtioTransport]string{
	TransportPCI:  "virtio-balloon-pci",
	TransportCCW:  "virtio-balloon-ccw",
	TransportMMIO: "virtio-balloon-device",
}

// QemuParams returns the qemu parameters built out of the BalloonDevice.
func (b BalloonDevice) QemuParams(config *Config) []string {
	var qemuParams []string
	var deviceParams []string

	deviceParams = append(deviceParams, b.deviceName(config))

	if b.ID != "" {
		deviceParams = append(deviceParams, "id="+b.ID)
	}

	if b.Transport.isVirtioPCI(config) && b.ROMFile != "" {
		deviceParams = append(deviceParams, fmt.Sprintf("romfile=%s", b.ROMFile))
	}

	if b.Transport.isVirtioCCW(config) {
		deviceParams = append(deviceParams, fmt.Sprintf("devno=%s", b.DevNo))
	}

	if b.DeflateOnOOM {
		deviceParams = append(deviceParams, "deflate-on-oom=on")
	} else {
		deviceParams = append(deviceParams, "deflate-on-oom=off")
	}
	if s := b.Transport.disableModern(config, b.DisableModern); s != "" {
		deviceParams = append(deviceParams, s)
	}
	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))

	return qemuParams
}

// Valid returns true if the balloonDevice structure is valid and complete.
func (b BalloonDevice) Valid() bool {
	return b.ID != ""
}

// deviceName returns the QEMU device name for the current combination of
// driver and transport.
func (b BalloonDevice) deviceName(config *Config) string {
	if b.Transport == "" {
		b.Transport = b.Transport.defaultTransport(config)
	}

	return BalloonDeviceTransport[b.Transport]
}

// IommuDev represents a Intel IOMMU Device
type IommuDev struct {
	Intremap    bool
	DeviceIotlb bool
	CachingMode bool
}

// Valid returns true if the IommuDev is valid
func (dev IommuDev) Valid() bool {
	return true
}

// deviceName the qemu device name
func (dev IommuDev) deviceName() string {
	return "intel-iommu"
}

// QemuParams returns the qemu parameters built out of the IommuDev.
func (dev IommuDev) QemuParams(_ *Config) []string {
	var qemuParams []string
	var deviceParams []string

	deviceParams = append(deviceParams, dev.deviceName())
	if dev.Intremap {
		deviceParams = append(deviceParams, "intremap=on")
	} else {
		deviceParams = append(deviceParams, "intremap=off")
	}

	if dev.DeviceIotlb {
		deviceParams = append(deviceParams, "device-iotlb=on")
	} else {
		deviceParams = append(deviceParams, "device-iotlb=off")
	}

	if dev.CachingMode {
		deviceParams = append(deviceParams, "caching-mode=on")
	} else {
		deviceParams = append(deviceParams, "caching-mode=off")
	}

	qemuParams = append(qemuParams, "-device")
	qemuParams = append(qemuParams, strings.Join(deviceParams, ","))
	return qemuParams
}

// RTCBaseType is the qemu RTC base time type.
type RTCBaseType string

// RTCClock is the qemu RTC clock type.
type RTCClock string

// RTCDriftFix is the qemu RTC drift fix type.
type RTCDriftFix string

const (
	// UTC is the UTC base time for qemu RTC.
	UTC RTCBaseType = "utc"

	// LocalTime is the local base time for qemu RTC.
	LocalTime RTCBaseType = "localtime"
)

const (
	// Host is for using the host clock as a reference.
	Host RTCClock = "host"

	// RT is for using the host monotonic clock as a reference.
	RT RTCClock = "rt"

	// VM is for using the guest clock as a reference
	VM RTCClock = "vm"
)

const (
	// Slew is the qemu RTC Drift fix mechanism.
	Slew RTCDriftFix = "slew"

	// NoDriftFix means we don't want/need to fix qemu's RTC drift.
	NoDriftFix RTCDriftFix = "none"
)

// RTC represents a qemu Real Time Clock configuration.
type RTC struct {
	// Base is the RTC start time.
	Base RTCBaseType

	// Clock is the is the RTC clock driver.
	Clock RTCClock

	// DriftFix is the drift fixing mechanism.
	DriftFix RTCDriftFix
}

// Valid returns true if the RTC structure is valid and complete.
func (rtc RTC) Valid() bool {
	if rtc.Clock != Host && rtc.Clock != RT && rtc.Clock != VM {
		return false
	}

	if rtc.DriftFix != Slew && rtc.DriftFix != NoDriftFix {
		return false
	}

	return true
}

// QMPSocketType is the type of socket used for QMP communication.
type QMPSocketType string

const (
	// Unix socket for QMP.
	Unix QMPSocketType = "unix"
)

// MonitorProtocol tells what protocol is used on a QMPSocket
type MonitorProtocol string

const (
	// Socket using a human-friendly text-based protocol.
	Hmp MonitorProtocol = "hmp"

	// Socket using a richer json-based protocol.
	Qmp MonitorProtocol = "qmp"

	// Same as Qmp with pretty json formatting.
	QmpPretty MonitorProtocol = "qmp-pretty"
)

// QMPSocket represents a qemu QMP or HMP socket configuration.
// nolint: govet
type QMPSocket struct {
	// Type is the socket type (e.g. "unix").
	Type QMPSocketType

	// Protocol is the protocol to be used on the socket.
	Protocol MonitorProtocol

	// QMP listener file descriptor to be passed to qemu
	FD *os.File

	// Name is the socket name.
	Name string

	// Server tells if this is a server socket.
	Server bool

	// NoWait tells if qemu should block waiting for a client to connect.
	NoWait bool
}

// Valid returns true if the QMPSocket structure is valid and complete.
func (qmp QMPSocket) Valid() bool {
	// Exactly one of Name of FD must be set.
	if qmp.Type == "" || (qmp.Name == "") == (qmp.FD == nil) {
		return false
	}

	if qmp.Type != Unix {
		return false
	}

	if qmp.Protocol != Hmp && qmp.Protocol != Qmp && qmp.Protocol != QmpPretty {
		return false
	}

	return true
}

// SMP is the multi processors configuration structure.
type SMP struct {
	// CPUs is the number of VCPUs made available to qemu.
	CPUs uint32

	// Cores is the number of cores made available to qemu.
	Cores uint32

	// Threads is the number of threads made available to qemu.
	Threads uint32

	// Sockets is the number of sockets made available to qemu.
	Sockets uint32

	// MaxCPUs is the maximum number of VCPUs that a VM can have.
	// This value, if non-zero, MUST BE equal to or greater than CPUs
	MaxCPUs uint32
}

// Memory is the guest memory configuration structure.
// nolint: govet
type Memory struct {
	// Size is the amount of memory made available to the guest.
	// It should be suffixed with M or G for sizes in megabytes or
	// gigabytes respectively.
	Size string

	// Slots is the amount of memory slots made available to the guest.
	Slots uint8

	// MaxMem is the maximum amount of memory that can be made available
	// to the guest through e.g. hot pluggable memory.
	MaxMem string

	// Path is the file path of the memory device. It points to a local
	// file path used by FileBackedMem.
	Path string
}

// Kernel is the guest kernel configuration structure.
type Kernel struct {
	// Path is the guest kernel path on the host filesystem.
	Path string

	// InitrdPath is the guest initrd path on the host filesystem.
	InitrdPath string

	// Params is the kernel parameters string.
	Params string
}

// FwCfg allows QEMU to pass entries to the guest
// File and Str are mutually exclusive
type FwCfg struct {
	Name string
	File string
	Str  string
}

// Valid returns true if the FwCfg structure is valid and complete.
func (fwcfg FwCfg) Valid() bool {
	if fwcfg.Name == "" {
		return false
	}

	if fwcfg.File != "" && fwcfg.Str != "" {
		return false
	}

	if fwcfg.File == "" && fwcfg.Str == "" {
		return false
	}

	return true
}

// QemuParams returns the qemu parameters built out of the FwCfg object
func (fwcfg FwCfg) QemuParams(config *Config) []string {
	var fwcfgParams []string
	var qemuParams []string

	for _, f := range config.FwCfg {
		if f.Name != "" {
			fwcfgParams = append(fwcfgParams, fmt.Sprintf("name=%s", f.Name))

			if f.File != "" {
				fwcfgParams = append(fwcfgParams, fmt.Sprintf("file=%s", f.File))
			}

			if f.Str != "" {
				fwcfgParams = append(fwcfgParams, fmt.Sprintf("string=%s", f.Str))
			}
		}

		qemuParams = append(qemuParams, "-fw_cfg")
		qemuParams = append(qemuParams, strings.Join(fwcfgParams, ","))
	}

	return qemuParams
}

// Knobs regroups a set of qemu boolean settings
type Knobs struct {
	// NoUserConfig prevents qemu from loading user config files.
	NoUserConfig bool

	// NoDefaults prevents qemu from creating default devices.
	NoDefaults bool

	// NoGraphic completely disables graphic output.
	NoGraphic bool

	// Both HugePages and MemPrealloc require the Memory.Size of the VM
	// to be set, as they need to reserve the memory upfront in order
	// for the VM to boot without errors.
	//
	// HugePages always results in memory pre-allocation.
	// However the setup is different from normal pre-allocation.
	// Hence HugePages has precedence over MemPrealloc
	// HugePages will pre-allocate all the RAM from huge pages
	HugePages bool

	// MemPrealloc will allocate all the RAM upfront
	MemPrealloc bool

	// FileBackedMem requires Memory.Size and Memory.Path of the VM to
	// be set.
	FileBackedMem bool

	// MemShared will set the memory device as shared.
	MemShared bool

	// Mlock will control locking of memory
	Mlock bool

	// Stopped will not start guest CPU at startup
	Stopped bool

	// Exit instead of rebooting
	// Prevents QEMU from rebooting in the event of a Triple Fault.
	NoReboot bool

	// IOMMUPlatform will enable IOMMU for supported devices
	IOMMUPlatform bool
}

// IOThread allows IO to be performed on a separate thread.
type IOThread struct {
	ID string
}

const (
	// MigrationFD is the migration incoming type based on open file descriptor.
	// Skip default 0 so that it must be set on purpose.
	MigrationFD = 1
	// MigrationExec is the migration incoming type based on commands.
	MigrationExec = 2
	// MigrationDefer is the defer incoming type
	MigrationDefer = 3
)

// Incoming controls migration source preparation
// nolint: govet
type Incoming struct {
	// Possible values are MigrationFD, MigrationExec
	MigrationType int
	// Only valid if MigrationType == MigrationFD
	FD *os.File
	// Only valid if MigrationType == MigrationExec
	Exec string
}

// Config is the qemu configuration structure.
// It allows for passing custom settings and parameters to the qemu API.
// nolint: govet
type Config struct {
	// Path is the qemu binary path.
	Path string

	// Ctx is the context used when launching qemu.
	Ctx context.Context

	// User ID.
	Uid uint32
	// Group ID.
	Gid uint32
	// Supplementary group IDs.
	Groups []uint32

	// Name is the qemu guest name
	Name string

	// UUID is the qemu process UUID.
	UUID string

	// CPUModel is the CPU model to be used by qemu.
	CPUModel string

	// SeccompSandbox is the qemu function which enables the seccomp feature
	SeccompSandbox string

	// Machine
	Machine Machine

	// QMPSockets is a slice of QMP socket description.
	QMPSockets []QMPSocket

	// Devices is a list of devices for qemu to create and drive.
	Devices []Device

	// RTC is the qemu Real Time Clock configuration
	RTC RTC

	// VGA is the qemu VGA mode.
	VGA string

	// Kernel is the guest kernel configuration.
	Kernel Kernel

	// Memory is the guest memory configuration.
	Memory Memory

	// SMP is the quest multi processors configuration.
	SMP SMP

	// GlobalParam is the -global parameter.
	GlobalParam string

	// Knobs is a set of qemu boolean settings.
	Knobs Knobs

	// Bios is the -bios parameter
	Bios string

	// PFlash specifies the parallel flash images (-pflash parameter)
	PFlash []string

	// Incoming controls migration source preparation
	Incoming Incoming

	// fds is a list of open file descriptors to be passed to the spawned qemu process
	fds []*os.File

	// FwCfg is the -fw_cfg parameter
	FwCfg []FwCfg

	IOThreads []IOThread

	// PidFile is the -pidfile parameter
	PidFile string

	qemuParams []string

	Debug bool
}

// appendFDs appends a list of arbitrary file descriptors to the qemu configuration and
// returns a slice of consecutive file descriptors that will be seen by the qemu process.
// Please see the comment below for details.
func (config *Config) appendFDs(fds []*os.File) []int {
	var fdInts []int

	oldLen := len(config.fds)

	config.fds = append(config.fds, fds...)

	// The magic 3 offset comes from https://golang.org/src/os/exec/exec.go:
	//     ExtraFiles specifies additional open files to be inherited by the
	//     new process. It does not include standard input, standard output, or
	//     standard error. If non-nil, entry i becomes file descriptor 3+i.
	// This means that arbitrary file descriptors fd0, fd1... fdN passed in
	// the array will be presented to the guest as consecutive descriptors
	// 3, 4... N+3. The golang library internally relies on dup2() to do
	// the renumbering.
	for i := range fds {
		fdInts = append(fdInts, oldLen+3+i)
	}

	return fdInts
}

func (config *Config) appendSeccompSandbox() {
	if config.SeccompSandbox != "" {
		config.qemuParams = append(config.qemuParams, "-sandbox")
		config.qemuParams = append(config.qemuParams, config.SeccompSandbox)
	}
}

func (config *Config) appendName() {
	if config.Name != "" {
		var nameParams []string
		nameParams = append(nameParams, config.Name)

		if config.Debug {
			nameParams = append(nameParams, "debug-threads=on")
		}

		config.qemuParams = append(config.qemuParams, "-name")
		config.qemuParams = append(config.qemuParams, strings.Join(nameParams, ","))
	}
}

func (config *Config) appendMachine() {
	if config.Machine.Type != "" {
		var machineParams []string

		machineParams = append(machineParams, config.Machine.Type)

		if config.Machine.Acceleration != "" {
			machineParams = append(machineParams, fmt.Sprintf("accel=%s", config.Machine.Acceleration))
		}

		if config.Machine.Options != "" {
			machineParams = append(machineParams, config.Machine.Options)
		}

		config.qemuParams = append(config.qemuParams, "-machine")
		config.qemuParams = append(config.qemuParams, strings.Join(machineParams, ","))
	}
}

func (config *Config) appendCPUModel() {
	if config.CPUModel != "" {
		config.qemuParams = append(config.qemuParams, "-cpu")
		config.qemuParams = append(config.qemuParams, config.CPUModel)
	}
}

func (config *Config) appendQMPSockets() {
	for _, q := range config.QMPSockets {
		if !q.Valid() {
			continue
		}

		var qmpParams []string
		if q.FD != nil {
			qemuFDs := config.appendFDs([]*os.File{q.FD})
			qmpParams = append([]string{}, fmt.Sprintf("%s:fd=%d", q.Type, qemuFDs[0]))
		} else {
			qmpParams = append([]string{}, fmt.Sprintf("%s:path=%s", q.Type, q.Name))
		}
		if q.Server {
			qmpParams = append(qmpParams, "server=on")
			if q.NoWait {
				qmpParams = append(qmpParams, "wait=off")
			}
		}

		switch q.Protocol {
		case Hmp:
			config.qemuParams = append(config.qemuParams, "-monitor")
		default:
			config.qemuParams = append(config.qemuParams, fmt.Sprintf("-%s", q.Protocol))
		}

		config.qemuParams = append(config.qemuParams, strings.Join(qmpParams, ","))
	}
}

func (config *Config) appendDevices(logger QMPLog) {
	if logger == nil {
		logger = qmpNullLogger{}
	}

	for _, d := range config.Devices {
		if !d.Valid() {
			logger.Errorf("vm device is not valid: %+v", d)
			continue
		}
		config.qemuParams = append(config.qemuParams, d.QemuParams(config)...)
	}
}

func (config *Config) appendUUID() {
	if config.UUID != "" {
		config.qemuParams = append(config.qemuParams, "-uuid")
		config.qemuParams = append(config.qemuParams, config.UUID)
	}
}

func (config *Config) appendMemory() {
	if config.Memory.Size != "" {
		var memoryParams []string

		memoryParams = append(memoryParams, config.Memory.Size)

		if config.Memory.Slots > 0 {
			memoryParams = append(memoryParams, fmt.Sprintf("slots=%d", config.Memory.Slots))
		}

		if config.Memory.MaxMem != "" {
			memoryParams = append(memoryParams, fmt.Sprintf("maxmem=%s", config.Memory.MaxMem))
		}

		config.qemuParams = append(config.qemuParams, "-m")
		config.qemuParams = append(config.qemuParams, strings.Join(memoryParams, ","))
	}
}

func (config *Config) appendCPUs() error {
	if config.SMP.CPUs > 0 {
		var SMPParams []string

		SMPParams = append(SMPParams, fmt.Sprintf("%d", config.SMP.CPUs))

		if config.SMP.Cores > 0 {
			SMPParams = append(SMPParams, fmt.Sprintf("cores=%d", config.SMP.Cores))
		}

		if config.SMP.Threads > 0 {
			SMPParams = append(SMPParams, fmt.Sprintf("threads=%d", config.SMP.Threads))
		}

		if config.SMP.Sockets > 0 {
			SMPParams = append(SMPParams, fmt.Sprintf("sockets=%d", config.SMP.Sockets))
		}

		if config.SMP.MaxCPUs > 0 {
			if config.SMP.MaxCPUs < config.SMP.CPUs {
				return fmt.Errorf("MaxCPUs %d must be equal to or greater than CPUs %d",
					config.SMP.MaxCPUs, config.SMP.CPUs)
			}
			SMPParams = append(SMPParams, fmt.Sprintf("maxcpus=%d", config.SMP.MaxCPUs))
		}

		config.qemuParams = append(config.qemuParams, "-smp")
		config.qemuParams = append(config.qemuParams, strings.Join(SMPParams, ","))
	}

	return nil
}

func (config *Config) appendRTC() {
	if !config.RTC.Valid() {
		return
	}

	var RTCParams []string

	RTCParams = append(RTCParams, fmt.Sprintf("base=%s", string(config.RTC.Base)))

	if config.RTC.DriftFix != "" {
		RTCParams = append(RTCParams, fmt.Sprintf("driftfix=%s", config.RTC.DriftFix))
	}

	if config.RTC.Clock != "" {
		RTCParams = append(RTCParams, fmt.Sprintf("clock=%s", config.RTC.Clock))
	}

	config.qemuParams = append(config.qemuParams, "-rtc")
	config.qemuParams = append(config.qemuParams, strings.Join(RTCParams, ","))
}

func (config *Config) appendGlobalParam() {
	if config.GlobalParam != "" {
		config.qemuParams = append(config.qemuParams, "-global")
		config.qemuParams = append(config.qemuParams, config.GlobalParam)
	}
}

func (config *Config) appendPFlashParam() {
	for _, p := range config.PFlash {
		config.qemuParams = append(config.qemuParams, "-pflash")
		config.qemuParams = append(config.qemuParams, p)
	}
}

func (config *Config) appendVGA() {
	if config.VGA != "" {
		config.qemuParams = append(config.qemuParams, "-vga")
		config.qemuParams = append(config.qemuParams, config.VGA)
	}
}

func (config *Config) appendKernel() {
	if config.Kernel.Path != "" {
		config.qemuParams = append(config.qemuParams, "-kernel")
		config.qemuParams = append(config.qemuParams, config.Kernel.Path)

		if config.Kernel.InitrdPath != "" {
			config.qemuParams = append(config.qemuParams, "-initrd")
			config.qemuParams = append(config.qemuParams, config.Kernel.InitrdPath)
		}

		if config.Kernel.Params != "" {
			config.qemuParams = append(config.qemuParams, "-append")
			config.qemuParams = append(config.qemuParams, config.Kernel.Params)
		}
	}
}

func (config *Config) appendMemoryKnobs() {
	if config.Memory.Size == "" {
		return
	}
	var objMemParam, numaMemParam string
	dimmName := "dimm1"
	if config.Knobs.HugePages {
		objMemParam = "memory-backend-file,id=" + dimmName + ",size=" + config.Memory.Size + ",mem-path=/dev/hugepages"
		numaMemParam = "node,memdev=" + dimmName
	} else if config.Knobs.FileBackedMem && config.Memory.Path != "" {
		objMemParam = "memory-backend-file,id=" + dimmName + ",size=" + config.Memory.Size + ",mem-path=" + config.Memory.Path
		numaMemParam = "node,memdev=" + dimmName
	} else {
		objMemParam = "memory-backend-ram,id=" + dimmName + ",size=" + config.Memory.Size
		numaMemParam = "node,memdev=" + dimmName
	}

	if config.Knobs.MemShared {
		objMemParam += ",share=on"
	}
	if config.Knobs.MemPrealloc {
		objMemParam += ",prealloc=on"
	}
	config.qemuParams = append(config.qemuParams, "-object")
	config.qemuParams = append(config.qemuParams, objMemParam)

	if isDimmSupported(config) {
		config.qemuParams = append(config.qemuParams, "-numa")
		config.qemuParams = append(config.qemuParams, numaMemParam)
	} else {
		config.qemuParams = append(config.qemuParams, "-machine")
		config.qemuParams = append(config.qemuParams, "memory-backend="+dimmName)
	}
}

func (config *Config) appendKnobs() {
	if config.Knobs.NoUserConfig {
		config.qemuParams = append(config.qemuParams, "-no-user-config")
	}

	if config.Knobs.NoDefaults {
		config.qemuParams = append(config.qemuParams, "-nodefaults")
	}

	if config.Knobs.NoGraphic {
		config.qemuParams = append(config.qemuParams, "-nographic")
	}

	if config.Knobs.NoReboot {
		config.qemuParams = append(config.qemuParams, "--no-reboot")
	}

	config.appendMemoryKnobs()

	if config.Knobs.Mlock {
		config.qemuParams = append(config.qemuParams, "-overcommit")
		config.qemuParams = append(config.qemuParams, "mem-lock=on")
	}

	if config.Knobs.Stopped {
		config.qemuParams = append(config.qemuParams, "-S")
	}
}

func (config *Config) appendBios() {
	if config.Bios != "" {
		config.qemuParams = append(config.qemuParams, "-bios")
		config.qemuParams = append(config.qemuParams, config.Bios)
	}
}

func (config *Config) appendIOThreads() {
	for _, t := range config.IOThreads {
		if t.ID != "" {
			config.qemuParams = append(config.qemuParams, "-object")
			config.qemuParams = append(config.qemuParams, fmt.Sprintf("iothread,id=%s", t.ID))
		}
	}
}

func (config *Config) appendIncoming() {
	var uri string
	switch config.Incoming.MigrationType {
	case MigrationExec:
		uri = fmt.Sprintf("exec:%s", config.Incoming.Exec)
	case MigrationFD:
		chFDs := config.appendFDs([]*os.File{config.Incoming.FD})
		uri = fmt.Sprintf("fd:%d", chFDs[0])
	case MigrationDefer:
		uri = "defer"
	default:
		return
	}
	config.qemuParams = append(config.qemuParams, "-S", "-incoming", uri)
}

func (config *Config) appendPidFile() {
	if config.PidFile != "" {
		config.qemuParams = append(config.qemuParams, "-pidfile")
		config.qemuParams = append(config.qemuParams, config.PidFile)
	}
}

func (config *Config) appendFwCfg(logger QMPLog) {
	if logger == nil {
		logger = qmpNullLogger{}
	}

	for _, f := range config.FwCfg {
		if !f.Valid() {
			logger.Errorf("fw_cfg is not valid: %+v", config.FwCfg)
			continue
		}

		config.qemuParams = append(config.qemuParams, f.QemuParams(config)...)
	}
}

// ********** kata-containers\src\runtime\virtcontainers\qemu.go **********
// QMPLog is a logging interface used by the qemu package to log various
// interesting pieces of information.  Rather than introduce a dependency
// on a given logging package, qemu presents this interface that allows
// clients to provide their own logging type which they can use to
// seamlessly integrate qemu's logs into their own logs.  A QMPLog
// implementation can be specified in the QMPConfig structure.
type QMPLog interface {
	// V returns true if the given argument is less than or equal
	// to the implementation's defined verbosity level.
	V(int32) bool

	// Infof writes informational output to the log.  A newline will be
	// added to the output if one is not provided.
	Infof(string, ...interface{})

	// Warningf writes warning output to the log.  A newline will be
	// added to the output if one is not provided.
	Warningf(string, ...interface{})

	// Errorf writes error output to the log.  A newline will be
	// added to the output if one is not provided.
	Errorf(string, ...interface{})
}

type qmpNullLogger struct{}

func (l qmpNullLogger) V(level int32) bool {
	return false
}

func (l qmpNullLogger) Infof(format string, v ...interface{}) {
}

func (l qmpNullLogger) Warningf(format string, v ...interface{}) {
}

func (l qmpNullLogger) Errorf(format string, v ...interface{}) {
}

// QMPConfig is a configuration structure that can be used to specify a
// logger and a channel to which logs and  QMP events are to be sent.  If
// neither of these fields are specified, or are set to nil, no logs will be
// written and no QMP events will be reported to the client.
type QMPConfig struct {
	// eventCh can be specified by clients who wish to receive QMP
	// events.
	EventCh chan<- QMPEvent

	// logger is used by the qmpStart function and all the go routines
	// it spawns to log information.
	Logger QMPLog

	// specify the capacity of buffer used by receive QMP response.
	MaxCapacity int
}

type qmpEventFilter struct {
	eventName string
	dataKey   string
	dataValue string
}

// QMPEvent contains a single QMP event, sent on the QMPConfig.EventCh channel.
// nolint: govet
type QMPEvent struct {
	// The name of the event, e.g., DEVICE_DELETED
	Name string

	// The data associated with the event.  The contents of this map are
	// unprocessed by the qemu package.  It is simply the result of
	// unmarshalling the QMP json event.  Here's an example map
	// map[string]interface{}{
	//	"driver": "virtio-blk-pci",
	//	"drive":  "drive_3437843748734873483",
	// }
	Data map[string]interface{}

	// The event's timestamp converted to a time.Time object.
	Timestamp time.Time
}

type qmpResult struct {
	response interface{}
	err      error
}

// nolint: govet
type qmpCommand struct {
	ctx            context.Context
	res            chan qmpResult
	name           string
	args           map[string]interface{}
	filter         *qmpEventFilter
	resultReceived bool
	oob            []byte
}

// QMPVersion contains the version number and the capabailities of a QEMU
// instance, as reported in the QMP greeting message.
// nolint: govet
type QMPVersion struct {
	Major        int
	Minor        int
	Micro        int
	Capabilities []string
}

// ********** kata-containers\src\runtime\pkg\katautils\create.go **********
var cvmSystemdKernelParam = []Param{
	{
		Key:   "systemd.unit",
		Value: systemdUnitName,
	},
	{
		Key:   "systemd.mask",
		Value: "systemd-networkd.service",
	},
	{
		Key:   "systemd.mask",
		Value: "systemd-networkd.socket",
	},
}

func getCVMKernelParams(needSystemd bool) []Param {
	p := []Param{}

	if needSystemd {
		p = append(p, cvmSystemdKernelParam...)
	}

	return p
}

func needSystemd(config HypervisorConfig) bool {
	return config.ImagePath != ""
}

// ********** kata-containers\src\runtime\virtcontainers\kata_agent.go **********
const (
	// KataEphemeralDevType creates a tmpfs backed volume for sharing files between containers.
	KataEphemeralDevType = "ephemeral"

	// KataLocalDevType creates a local directory inside the VM for sharing files between
	// containers.
	KataLocalDevType = "local"

	// Allocating an FSGroup that owns the pod's volumes
	fsGid = "fsgid"

	// path to vfio devices
	vfioPath = "/dev/vfio/"

	VirtualVolumePrefix = "io.katacontainers.volume="

	// enable debug console
	kernelParamDebugConsole           = "agent.debug_console"
	kernelParamDebugConsoleVPort      = "agent.debug_console_vport"
	kernelParamDebugConsoleVPortValue = "1026"

	// Default SELinux type applied to the container process inside guest
	defaultSeLinuxContainerType = "container_t"
)

// KataAgentKernelParams returns a list of Kata Agent specific kernel
// parameters.
func KataAgentKernelParams(config KataAgentConfig) []Param {
	var params []Param

	if config.Debug {
		params = append(params, Param{Key: "agent.log", Value: "debug"})
	}

	if config.Trace {
		params = append(params, Param{Key: "agent.trace", Value: "true"})
	}

	if config.ContainerPipeSize > 0 {
		containerPipeSize := strconv.FormatUint(uint64(config.ContainerPipeSize), 10)
		params = append(params, Param{Key: vcAnnotations.ContainerPipeSizeKernelParam, Value: containerPipeSize})
	}

	if config.EnableDebugConsole {
		params = append(params, Param{Key: kernelParamDebugConsole, Value: ""})
		params = append(params, Param{Key: kernelParamDebugConsoleVPort, Value: kernelParamDebugConsoleVPortValue})
	}

	if config.CdhApiTimeout > 0 {
		cdhApiTimeout := strconv.FormatUint(uint64(config.CdhApiTimeout), 10)
		params = append(params, Param{Key: vcAnnotations.CdhApiTimeoutKernelParam, Value: cdhApiTimeout})
	}

	return params
}

// KataAgentConfig is a structure storing information needed
// to reach the Kata Containers agent.
type KataAgentConfig struct {
	KernelModules      []string
	ContainerPipeSize  uint32
	DialTimeout        uint32
	CdhApiTimeout      uint32
	LongLiveConn       bool
	Debug              bool
	Trace              bool
	EnableDebugConsole bool
	Policy             string
}

// ********** kata-containers\src\runtime\pkg\katautils\config.go **********
type tomlConfig struct {
	Hypervisor map[string]hypervisor
	Agent      map[string]agent
	Factory    factory
	Runtime    runtime
}

type factory struct {
	TemplatePath    string `toml:"template_path"`
	VMCacheEndpoint string `toml:"vm_cache_endpoint"`
	VMCacheNumber   uint   `toml:"vm_cache_number"`
	Template        bool   `toml:"enable_template"`
}

type hypervisor struct {
	Path                           string                    `toml:"path"`
	JailerPath                     string                    `toml:"jailer_path"`
	Kernel                         string                    `toml:"kernel"`
	Initrd                         string                    `toml:"initrd"`
	Image                          string                    `toml:"image"`
	RootfsType                     string                    `toml:"rootfs_type"`
	Firmware                       string                    `toml:"firmware"`
	FirmwareVolume                 string                    `toml:"firmware_volume"`
	MachineAccelerators            string                    `toml:"machine_accelerators"`
	CPUFeatures                    string                    `toml:"cpu_features"`
	KernelParams                   string                    `toml:"kernel_params"`
	MachineType                    string                    `toml:"machine_type"`
	QgsPort                        uint32                    `toml:"tdx_quote_generation_service_socket_port"`
	BlockDeviceDriver              string                    `toml:"block_device_driver"`
	EntropySource                  string                    `toml:"entropy_source"`
	SharedFS                       string                    `toml:"shared_fs"`
	VirtioFSDaemon                 string                    `toml:"virtio_fs_daemon"`
	VirtioFSCache                  string                    `toml:"virtio_fs_cache"`
	VhostUserStorePath             string                    `toml:"vhost_user_store_path"`
	FileBackedMemRootDir           string                    `toml:"file_mem_backend"`
	GuestHookPath                  string                    `toml:"guest_hook_path"`
	GuestMemoryDumpPath            string                    `toml:"guest_memory_dump_path"`
	SeccompSandbox                 string                    `toml:"seccompsandbox"`
	BlockDeviceAIO                 string                    `toml:"block_device_aio"`
	RemoteHypervisorSocket         string                    `toml:"remote_hypervisor_socket"`
	SnpIdBlock                     string                    `toml:"snp_id_block"`
	SnpIdAuth                      string                    `toml:"snp_id_auth"`
	HypervisorPathList             []string                  `toml:"valid_hypervisor_paths"`
	JailerPathList                 []string                  `toml:"valid_jailer_paths"`
	VirtioFSDaemonList             []string                  `toml:"valid_virtio_fs_daemon_paths"`
	VirtioFSExtraArgs              []string                  `toml:"virtio_fs_extra_args"`
	PFlashList                     []string                  `toml:"pflashes"`
	VhostUserStorePathList         []string                  `toml:"valid_vhost_user_store_paths"`
	FileBackedMemRootList          []string                  `toml:"valid_file_mem_backends"`
	EntropySourceList              []string                  `toml:"valid_entropy_sources"`
	EnableAnnotations              []string                  `toml:"enable_annotations"`
	RxRateLimiterMaxRate           uint64                    `toml:"rx_rate_limiter_max_rate"`
	TxRateLimiterMaxRate           uint64                    `toml:"tx_rate_limiter_max_rate"`
	MemOffset                      uint64                    `toml:"memory_offset"`
	DefaultMaxMemorySize           uint64                    `toml:"default_maxmemory"`
	DiskRateLimiterBwMaxRate       int64                     `toml:"disk_rate_limiter_bw_max_rate"`
	DiskRateLimiterBwOneTimeBurst  int64                     `toml:"disk_rate_limiter_bw_one_time_burst"`
	DiskRateLimiterOpsMaxRate      int64                     `toml:"disk_rate_limiter_ops_max_rate"`
	DiskRateLimiterOpsOneTimeBurst int64                     `toml:"disk_rate_limiter_ops_one_time_burst"`
	NetRateLimiterBwMaxRate        int64                     `toml:"net_rate_limiter_bw_max_rate"`
	NetRateLimiterBwOneTimeBurst   int64                     `toml:"net_rate_limiter_bw_one_time_burst"`
	NetRateLimiterOpsMaxRate       int64                     `toml:"net_rate_limiter_ops_max_rate"`
	NetRateLimiterOpsOneTimeBurst  int64                     `toml:"net_rate_limiter_ops_one_time_burst"`
	HypervisorLoglevel             uint32                    `toml:"hypervisor_loglevel"`
	VirtioFSCacheSize              uint32                    `toml:"virtio_fs_cache_size"`
	VirtioFSQueueSize              uint32                    `toml:"virtio_fs_queue_size"`
	DefaultMaxVCPUs                uint32                    `toml:"default_maxvcpus"`
	MemorySize                     uint32                    `toml:"default_memory"`
	MemSlots                       uint32                    `toml:"memory_slots"`
	DefaultBridges                 uint32                    `toml:"default_bridges"`
	Msize9p                        uint32                    `toml:"msize_9p"`
	RemoteHypervisorTimeout        uint32                    `toml:"remote_hypervisor_timeout"`
	NumVCPUs                       float32                   `toml:"default_vcpus"`
	BlockDeviceCacheSet            bool                      `toml:"block_device_cache_set"`
	BlockDeviceCacheDirect         bool                      `toml:"block_device_cache_direct"`
	BlockDeviceCacheNoflush        bool                      `toml:"block_device_cache_noflush"`
	EnableVhostUserStore           bool                      `toml:"enable_vhost_user_store"`
	VhostUserDeviceReconnect       uint32                    `toml:"vhost_user_reconnect_timeout_sec"`
	DisableBlockDeviceUse          bool                      `toml:"disable_block_device_use"`
	MemPrealloc                    bool                      `toml:"enable_mem_prealloc"`
	HugePages                      bool                      `toml:"enable_hugepages"`
	VirtioMem                      bool                      `toml:"enable_virtio_mem"`
	IOMMU                          bool                      `toml:"enable_iommu"`
	IOMMUPlatform                  bool                      `toml:"enable_iommu_platform"`
	Debug                          bool                      `toml:"enable_debug"`
	DisableNestingChecks           bool                      `toml:"disable_nesting_checks"`
	EnableIOThreads                bool                      `toml:"enable_iothreads"`
	DisableImageNvdimm             bool                      `toml:"disable_image_nvdimm"`
	HotPlugVFIO                    gt_config.PCIePort           `toml:"hot_plug_vfio"`
	ColdPlugVFIO                   gt_config.PCIePort           `toml:"cold_plug_vfio"`
	PCIeRootPort                   uint32                    `toml:"pcie_root_port"`
	PCIeSwitchPort                 uint32                    `toml:"pcie_switch_port"`
	DisableVhostNet                bool                      `toml:"disable_vhost_net"`
	GuestMemoryDumpPaging          bool                      `toml:"guest_memory_dump_paging"`
	ConfidentialGuest              bool                      `toml:"confidential_guest"`
	SevSnpGuest                    bool                      `toml:"sev_snp_guest"`
	GuestSwap                      bool                      `toml:"enable_guest_swap"`
	Rootless                       bool                      `toml:"rootless"`
	DisableSeccomp                 bool                      `toml:"disable_seccomp"`
	DisableSeLinux                 bool                      `toml:"disable_selinux"`
	DisableGuestSeLinux            bool                      `toml:"disable_guest_selinux"`
	LegacySerial                   bool                      `toml:"use_legacy_serial"`
	ExtraMonitorSocket             govmmQemu.MonitorProtocol `toml:"extra_monitor_socket"`
}

type runtime struct {
	InterNetworkModel         string   `toml:"internetworking_model"`
	JaegerEndpoint            string   `toml:"jaeger_endpoint"`
	JaegerUser                string   `toml:"jaeger_user"`
	JaegerPassword            string   `toml:"jaeger_password"`
	VfioMode                  string   `toml:"vfio_mode"`
	GuestSeLinuxLabel         string   `toml:"guest_selinux_label"`
	SandboxBindMounts         []string `toml:"sandbox_bind_mounts"`
	Experimental              []string `toml:"experimental"`
	Tracing                   bool     `toml:"enable_tracing"`
	DisableNewNetNs           bool     `toml:"disable_new_netns"`
	DisableGuestSeccomp       bool     `toml:"disable_guest_seccomp"`
	EnableVCPUsPinning        bool     `toml:"enable_vcpus_pinning"`
	Debug                     bool     `toml:"enable_debug"`
	SandboxCgroupOnly         bool     `toml:"sandbox_cgroup_only"`
	StaticSandboxResourceMgmt bool     `toml:"static_sandbox_resource_mgmt"`
	EnablePprof               bool     `toml:"enable_pprof"`
	DisableGuestEmptyDir      bool     `toml:"disable_guest_empty_dir"`
	CreateContainerTimeout    uint64   `toml:"create_container_timeout"`
	DanConf                   string   `toml:"dan_conf"`
}

type agent struct {
	KernelModules       []string `toml:"kernel_modules"`
	Debug               bool     `toml:"enable_debug"`
	Tracing             bool     `toml:"enable_tracing"`
	DebugConsoleEnabled bool     `toml:"debug_console_enabled"`
	DialTimeout         uint32   `toml:"dial_timeout"`
	CdhApiTimeout       uint32   `toml:"cdh_api_timeout"`
}

func (orig *tomlConfig) Clone() tomlConfig {
	clone := *orig
	clone.Hypervisor = make(map[string]hypervisor)
	clone.Agent = make(map[string]agent)

	for key, value := range orig.Hypervisor {
		clone.Hypervisor[key] = value
	}
	for key, value := range orig.Agent {
		clone.Agent[key] = value
	}
	return clone
}

type image struct {
	Provision           string `toml:"provision"`
	ServiceOffload      bool   `toml:"service_offload"`
	ImageRequestTimeout uint64 `toml:"image_request_timeout"`
}

// default path
var DEFAULTRUNTIMECONFIGURATION = "/usr/share/defaults/kata-containers/configuration.toml"

// Alternate config file that takes precedence over
// defaultRuntimeConfiguration.
var DEFAULTSYSCONFRUNTIMECONFIGURATION = "/etc/kata-containers/configuration.toml"
var defaultHypervisorPath = "/usr/bin/qemu-system-x86_64"
var defaultHypervisorCtlPath = "/usr/bin/acrnctl"
var defaultJailerPath = "/usr/bin/jailer"
var defaultImagePath = "/usr/share/kata-containers/kata-containers.img"
var defaultKernelPath = "/usr/share/kata-containers/vmlinuz.container"
var defaultInitrdPath = "/usr/share/kata-containers/kata-containers-initrd.img"
var defaultRootfsType = "ext4"
var defaultFirmwarePath = ""
var defaultFirmwareVolumePath = ""
var defaultMachineAccelerators = ""
var defaultCPUFeatures = ""
var systemdUnitName = "kata-containers.target"

var defaultGuestType = ""
var defaultPlatformType = "kp920x"

const defaultKernelParams = ""
const defaultMachineType = "q35"

const defaultVCPUCount uint32 = 1
const defaultMaxVCPUCount uint32 = 0
const defaultMemSize uint32 = 2048 // MiB
const defaultMemSlots uint32 = 10
const defaultMemOffset uint64 = 0 // MiB
const defaultVirtioMem bool = false
const defaultBridgesCount uint32 = 1
const defaultInterNetworkingModel = "tcfilter"
const defaultDisableBlockDeviceUse bool = false
const defaultBlockDeviceDriver = "virtio-scsi"
const defaultBlockDeviceAIO string = "io_uring"
const defaultBlockDeviceCacheSet bool = false
const defaultBlockDeviceCacheDirect bool = false
const defaultBlockDeviceCacheNoflush bool = false
const defaultEnableIOThreads bool = false
const defaultEnableMemPrealloc bool = false
const defaultEnableHugePages bool = false
const defaultEnableIOMMU bool = false
const defaultEnableIOMMUPlatform bool = false
const defaultFileBackedMemRootDir string = ""
const defaultEnableDebug bool = false
const defaultDisableNestingChecks bool = false
const defaultMsize9p uint32 = 8192
const defaultEntropySource = "/dev/urandom"
const defaultGuestHookPath string = ""
const defaultVirtioFSCacheMode = "never"
const defaultDisableImageNvdimm = false
const defaultVhostUserStorePath string = "/var/run/kata-containers/vhost-user/"
const defaultVhostUserDeviceReconnect = 0
const defaultRxRateLimiterMaxRate = uint64(0)
const defaultTxRateLimiterMaxRate = uint64(0)
const defaultConfidentialGuest = false
const defaultSevSnpGuest = false
const defaultGuestSwap = false
const defaultRootlessHypervisor = false
const defaultDisableSeccomp = false
const defaultDisableGuestSeLinux = true
const defaultVfioMode = "guest-kernel"
const defaultLegacySerial = false
const defaultGuestPreAttestation = false
const defaultGuestPreAttestationURI string = ""
const defaultGuestPreAttestationMode string = ""
const defaultGuestPreAttestationKeyset string = ""
const defaultSEVCertChainPath string = ""
const defaultSEVGuestPolicy uint32 = 0
const defaultSNPGuestPolicy uint64 = 0x30000
const MinHypervisorMemory = 256
const maxPCIBridges uint32 = 5
const qemuHypervisorTableType = "qemu"
const VHostVSockDevicePath = "/dev/vhost-vsock"
const defaultkernelParamDebugConsole = true
const maxPCIeRootPorts   uint32 = 16
const maxPCIeSwitchPorts uint32 = 16
const maxHypervisorLoglevel uint32 = 3
const errInvalidHypervisorPrefix = "configuration file contains invalid hypervisor section"
const defaultQgsPort = 4050
const defaultRemoteHypervisorSocket = "/run/peerpod/hypervisor.sock"
const defaultRemoteHypervisorTimeout = 600

var defaultSGXEPCSize = int64(0)

const defaultTemplatePath string = "/run/vc/vm/template"
const defaultVMCacheEndpoint string = "/var/run/kata-containers/cache.sock"

// Default config file used by stateless systems.
var defaultRuntimeConfiguration = "/usr/share/defaults/kata-containers/configuration.toml"

const defaultHotPlugVFIO = gt_config.NoPort
const defaultColdPlugVFIO = gt_config.NoPort

// ResolvePath returns the fully resolved and expanded value of the
// specified path.
func ResolvePath(path string) (string, error) {
	if path == "" {
		return "", fmt.Errorf("path must be specified")
	}

	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}

	resolved, err := filepath.EvalSymlinks(absolute)
	if err != nil {
		if os.IsNotExist(err) {
			// Make the error clearer than the default
			return "", fmt.Errorf("file %v does not exist", absolute)
		}

		return "", err
	}

	return resolved, nil
}

func (h hypervisor) path() (string, error) {
	p := h.Path

	if h.Path == "" {
		p = defaultHypervisorPath
	}

	return ResolvePath(p)
}

func (h hypervisor) jailerPath() (string, error) {
	p := h.JailerPath

	if h.JailerPath == "" {
		return "", nil
	}

	return ResolvePath(p)
}

func (h hypervisor) kernel() (string, error) {
	p := h.Kernel

	if p == "" {
		p = defaultKernelPath
	}

	return ResolvePath(p)
}

func (h hypervisor) initrd() (string, error) {
	p := h.Initrd

	if p == "" {
		return "", nil
	}

	return ResolvePath(p)
}

func (h hypervisor) image() (string, error) {
	p := h.Image

	if p == "" {
		return "", nil
	}

	return ResolvePath(p)
}

func (h hypervisor) rootfsType() (string, error) {
	p := h.RootfsType

	if p == "" {
		p = "ext4"
	}

	return p, nil
}

func (h hypervisor) firmware() (string, error) {
	p := h.Firmware

	if p == "" {
		if defaultFirmwarePath == "" {
			return "", nil
		}
		p = defaultFirmwarePath
	}

	return ResolvePath(p)
}

func (h hypervisor) coldPlugVFIO() gt_config.PCIePort {
	if h.ColdPlugVFIO == "" {
		return defaultColdPlugVFIO
	}
	return h.ColdPlugVFIO
}
func (h hypervisor) hotPlugVFIO() gt_config.PCIePort {
	if h.HotPlugVFIO == "" {
		return defaultHotPlugVFIO
	}
	return h.HotPlugVFIO
}

func (h hypervisor) pcieRootPort() uint32 {
	if h.PCIeRootPort > maxPCIeRootPorts {
		return maxPCIeRootPorts
	}
	return h.PCIeRootPort
}

func (h hypervisor) pcieSwitchPort() uint32 {
	if h.PCIeSwitchPort > maxPCIeSwitchPorts {
		return maxPCIeSwitchPorts
	}
	return h.PCIeSwitchPort
}

func (h hypervisor) firmwareVolume() (string, error) {
	p := h.FirmwareVolume

	if p == "" {
		if defaultFirmwareVolumePath == "" {
			return "", nil
		}
		p = defaultFirmwareVolumePath
	}

	return ResolvePath(p)
}

func (h hypervisor) PFlash() ([]string, error) {
	pflashes := h.PFlashList

	if len(pflashes) == 0 {
		return []string{}, nil
	}

	for _, pflash := range pflashes {
		_, err := ResolvePath(pflash)
		if err != nil {
			return []string{}, fmt.Errorf("failed to resolve path: %s: %v", pflash, err)
		}
	}

	return pflashes, nil
}

func (h hypervisor) machineAccelerators() string {
	var machineAccelerators string
	for _, accelerator := range strings.Split(h.MachineAccelerators, ",") {
		if accelerator != "" {
			machineAccelerators += strings.TrimSpace(accelerator) + ","
		}
	}

	machineAccelerators = strings.Trim(machineAccelerators, ",")

	return machineAccelerators
}

func (h hypervisor) cpuFeatures() string {
	var cpuFeatures string
	for _, feature := range strings.Split(h.CPUFeatures, ",") {
		if feature != "" {
			cpuFeatures += strings.TrimSpace(feature) + ","
		}
	}

	cpuFeatures = strings.Trim(cpuFeatures, ",")

	return cpuFeatures
}

func (h hypervisor) kernelParams() string {
	if h.KernelParams == "" {
		return defaultKernelParams
	}

	return h.KernelParams
}

func (h hypervisor) machineType() string {
	if h.MachineType == "" {
		return defaultMachineType
	}

	return h.MachineType
}

func (h hypervisor) qgsPort() uint32 {
	if h.QgsPort == 0 {
		return defaultQgsPort
	}

	return h.QgsPort
}

func (h hypervisor) GetEntropySource() string {
	if h.EntropySource == "" {
		return defaultEntropySource
	}

	return h.EntropySource
}

var procCPUInfo = "/proc/cpuinfo"

func getHostCPUs() uint32 {
	cpuInfo, err := os.ReadFile(procCPUInfo)
	if err != nil {
		kataUtilsLogger.Warn("unable to read /proc/cpuinfo to determine cpu count - using go runtime value instead")
		return uint32(goruntime.NumCPU())
	}

	cores := 0
	lines := strings.Split(string(cpuInfo), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "processor") {
			cores++
		}
	}

	return uint32(cores)
}

// Current cpu number should not larger than defaultMaxVCPUs()
func getCurrentCpuNum() uint32 {
	var cpu uint32
	h := hypervisor{}

	cpu = getHostCPUs()
	if cpu > h.defaultMaxVCPUs() {
		cpu = h.defaultMaxVCPUs()
	}

	return cpu
}

func (h hypervisor) defaultVCPUs() float32 {
	numCPUs := float32(getCurrentCpuNum())

	if h.NumVCPUs < 0 || h.NumVCPUs > numCPUs {
		return numCPUs
	}
	if h.NumVCPUs == 0 { // or unspecified
		return float32(defaultVCPUCount)
	}

	return h.NumVCPUs
}

func (h hypervisor) defaultMaxVCPUs() uint32 {
	numcpus := getHostCPUs()
	maxvcpus := govmm.MaxVCPUs()
	reqVCPUs := h.DefaultMaxVCPUs

	//don't exceed the number of physical CPUs. If a default is not provided, use the
	// numbers of physical CPUs
	if reqVCPUs >= numcpus || reqVCPUs == 0 {
		reqVCPUs = numcpus
	}

	// Don't exceed the maximum number of vCPUs supported by hypervisor
	if reqVCPUs > maxvcpus {
		return maxvcpus
	}

	return reqVCPUs
}

func (h hypervisor) defaultMemSz() uint32 {
	if h.MemorySize < vc.MinHypervisorMemory {
		return defaultMemSize // MiB
	}

	return h.MemorySize
}

func (h hypervisor) defaultMemSlots() uint32 {
	slots := h.MemSlots
	if slots == 0 {
		slots = defaultMemSlots
	}

	return slots
}

func (h hypervisor) defaultMemOffset() uint64 {
	offset := h.MemOffset
	if offset == 0 {
		offset = defaultMemOffset
	}

	return offset
}

func (h hypervisor) defaultMaxMemSz() uint64 {
	hostMemory := memory.TotalMemory() / 1024 / 1024 //MiB

	if h.DefaultMaxMemorySize == 0 {
		return hostMemory
	}

	if h.DefaultMaxMemorySize > hostMemory {
		return hostMemory
	}

	return h.DefaultMaxMemorySize
}

func (h hypervisor) defaultBridges() uint32 {
	if h.DefaultBridges == 0 {
		return defaultBridgesCount
	}

	if h.DefaultBridges > maxPCIBridges {
		return maxPCIBridges
	}

	return h.DefaultBridges
}

func (h hypervisor) defaultHypervisorLoglevel() uint32 {
	if h.HypervisorLoglevel > maxHypervisorLoglevel {
		return maxHypervisorLoglevel
	}

	return h.HypervisorLoglevel
}

func (h hypervisor) defaultVirtioFSCache() string {
	if h.VirtioFSCache == "" {
		return defaultVirtioFSCacheMode
	}

	return h.VirtioFSCache
}

func (h hypervisor) blockDeviceDriver() (string, error) {
	supportedBlockDrivers := []string{gt_config.VirtioSCSI, gt_config.VirtioBlock, gt_config.VirtioMmio, gt_config.Nvdimm, gt_config.VirtioBlockCCW}

	if h.BlockDeviceDriver == "" {
		return defaultBlockDeviceDriver, nil
	}

	for _, b := range supportedBlockDrivers {
		if b == h.BlockDeviceDriver {
			return h.BlockDeviceDriver, nil
		}
	}

	return "", fmt.Errorf("Invalid hypervisor block storage driver %v specified (supported drivers: %v)", h.BlockDeviceDriver, supportedBlockDrivers)
}

func (h hypervisor) blockDeviceAIO() (string, error) {
	supportedBlockAIO := []string{gt_config.AIOIOUring, gt_config.AIONative, gt_config.AIOThreads}

	if h.BlockDeviceAIO == "" {
		return defaultBlockDeviceAIO, nil
	}

	for _, b := range supportedBlockAIO {
		if b == h.BlockDeviceAIO {
			return h.BlockDeviceAIO, nil
		}
	}

	return "", fmt.Errorf("Invalid hypervisor block storage I/O mechanism  %v specified (supported AIO: %v)", h.BlockDeviceAIO, supportedBlockAIO)
}

func (h hypervisor) extraMonitorSocket() (govmmQemu.MonitorProtocol, error) {
	supportedExtraMonitor := []govmmQemu.MonitorProtocol{govmmQemu.Hmp, govmmQemu.Qmp, govmmQemu.QmpPretty}

	if h.ExtraMonitorSocket == "" {
		return "", nil
	}

	for _, extra := range supportedExtraMonitor {
		if extra == h.ExtraMonitorSocket {
			return extra, nil
		}
	}

	return "", fmt.Errorf("Invalid hypervisor extra monitor socket %v specified (supported values: %v)", h.ExtraMonitorSocket, supportedExtraMonitor)
}

func (h hypervisor) sharedFS() (string, error) {
	supportedSharedFS := []string{gt_config.Virtio9P, gt_config.VirtioFS, gt_config.VirtioFSNydus, gt_config.NoSharedFS}

	if h.SharedFS == "" {
		return gt_config.VirtioFS, nil
	}

	for _, fs := range supportedSharedFS {
		if fs == h.SharedFS {
			return h.SharedFS, nil
		}
	}

	return "", fmt.Errorf("Invalid hypervisor shared file system %v specified (supported file systems: %v)", h.SharedFS, supportedSharedFS)
}

func (h hypervisor) msize9p() uint32 {
	if h.Msize9p == 0 {
		return defaultMsize9p
	}

	return h.Msize9p
}

func (h hypervisor) guestHookPath() string {
	if h.GuestHookPath == "" {
		return defaultGuestHookPath
	}
	return h.GuestHookPath
}

func (h hypervisor) vhostUserStorePath() string {
	if h.VhostUserStorePath == "" {
		return defaultVhostUserStorePath
	}
	return h.VhostUserStorePath
}

func (h hypervisor) getDiskRateLimiterBwMaxRate() int64 {
	return h.DiskRateLimiterBwMaxRate
}

var kataUtilsLogger = logrus.NewEntry(logrus.New())

func (h hypervisor) getDiskRateLimiterBwOneTimeBurst() int64 {
	if h.DiskRateLimiterBwOneTimeBurst != 0 && h.getDiskRateLimiterBwMaxRate() == 0 {
		kataUtilsLogger.Warn("The DiskRateLimiterBwOneTimeBurst is set but DiskRateLimiterBwMaxRate is not set, this option will be ignored.")

		h.DiskRateLimiterBwOneTimeBurst = 0
	}

	return h.DiskRateLimiterBwOneTimeBurst
}

func (h hypervisor) getDiskRateLimiterOpsMaxRate() int64 {
	return h.DiskRateLimiterOpsMaxRate
}

func (h hypervisor) getDiskRateLimiterOpsOneTimeBurst() int64 {
	if h.DiskRateLimiterOpsOneTimeBurst != 0 && h.getDiskRateLimiterOpsMaxRate() == 0 {
		kataUtilsLogger.Warn("The DiskRateLimiterOpsOneTimeBurst is set but DiskRateLimiterOpsMaxRate is not set, this option will be ignored.")

		h.DiskRateLimiterOpsOneTimeBurst = 0
	}

	return h.DiskRateLimiterOpsOneTimeBurst
}

func (h hypervisor) getRxRateLimiterCfg() uint64 {
	return h.RxRateLimiterMaxRate
}

func (h hypervisor) getTxRateLimiterCfg() uint64 {
	return h.TxRateLimiterMaxRate
}

func (h hypervisor) getNetRateLimiterBwMaxRate() int64 {
	return h.NetRateLimiterBwMaxRate
}

func (h hypervisor) getNetRateLimiterBwOneTimeBurst() int64 {
	if h.NetRateLimiterBwOneTimeBurst != 0 && h.getNetRateLimiterBwMaxRate() == 0 {
		kataUtilsLogger.Warn("The NetRateLimiterBwOneTimeBurst is set but NetRateLimiterBwMaxRate is not set, this option will be ignored.")

		h.NetRateLimiterBwOneTimeBurst = 0
	}

	return h.NetRateLimiterBwOneTimeBurst
}

func (h hypervisor) getNetRateLimiterOpsMaxRate() int64 {
	return h.NetRateLimiterOpsMaxRate
}

func (h hypervisor) getNetRateLimiterOpsOneTimeBurst() int64 {
	if h.NetRateLimiterOpsOneTimeBurst != 0 && h.getNetRateLimiterOpsMaxRate() == 0 {
		kataUtilsLogger.Warn("The NetRateLimiterOpsOneTimeBurst is set but NetRateLimiterOpsMaxRate is not set, this option will be ignored.")

		h.NetRateLimiterOpsOneTimeBurst = 0
	}

	return h.NetRateLimiterOpsOneTimeBurst
}

func (h hypervisor) getIOMMUPlatform() bool {
	if h.IOMMUPlatform {
		kataUtilsLogger.Info("IOMMUPlatform is enabled by default.")
	} else {
		kataUtilsLogger.Info("IOMMUPlatform is disabled by default.")
	}
	return h.IOMMUPlatform
}

func (h hypervisor) getRemoteHypervisorSocket() string {
	if h.RemoteHypervisorSocket == "" {
		return defaultRemoteHypervisorSocket
	}
	return h.RemoteHypervisorSocket
}

func (h hypervisor) getRemoteHypervisorTimeout() uint32 {
	if h.RemoteHypervisorTimeout == 0 {
		return defaultRemoteHypervisorTimeout
	}
	return h.RemoteHypervisorTimeout
}

func (a agent) debugConsoleEnabled() bool {
	return a.DebugConsoleEnabled
}

func (a agent) dialTimout() uint32 {
	return a.DialTimeout
}

func (a agent) cdhApiTimout() uint32 {
	return a.CdhApiTimeout
}

func (a agent) debug() bool {
	return a.Debug
}

func (a agent) trace() bool {
	return a.Tracing
}

func (a agent) kernelModules() []string {
	return a.KernelModules
}

// SerializeParams converts []Param to []string
func SerializeParams(params []Param, delim string) []string {
	var parameters []string

	for _, p := range params {
		if p.Key == "" && p.Value == "" {
			continue
		} else if p.Key == "" {
			parameters = append(parameters, fmt.Sprint(p.Value))
		} else if p.Value == "" {
			parameters = append(parameters, fmt.Sprint(p.Key))
		} else if delim == "" {
			parameters = append(parameters, fmt.Sprint(p.Key))
			parameters = append(parameters, fmt.Sprint(p.Value))
		} else {
			parameters = append(parameters, fmt.Sprintf("%s%s%s", p.Key, delim, p.Value))
		}
	}

	return parameters
}

// DeserializeParams converts []string to []Param
func DeserializeParams(parameters []string) []Param {
	var params []Param

	for _, param := range parameters {
		if param == "" {
			continue
		}
		p := strings.SplitN(param, "=", 2)
		if len(p) == 2 {
			params = append(params, Param{Key: p[0], Value: p[1]})
		} else {
			params = append(params, Param{Key: p[0], Value: ""})
		}
	}

	return params
}

func newQemuHypervisorConfig(h hypervisor) (HypervisorConfig, error) {
	hypervisor, err := h.path()
	if err != nil {
		return HypervisorConfig{}, err
	}

	kernel, err := h.kernel()
	if err != nil {
		return HypervisorConfig{}, err
	}

	initrd, err := h.initrd()
	if err != nil {
		return HypervisorConfig{}, err
	}

	image, err := h.image()
	if err != nil {
		return HypervisorConfig{}, err
	}

	rootfsType, err := h.rootfsType()
	if err != nil {
		return HypervisorConfig{}, err
	}

	pflashes, err := h.PFlash()
	if err != nil {
		return HypervisorConfig{}, err
	}

	firmware, err := h.firmware()
	if err != nil {
		return HypervisorConfig{}, err
	}

	firmwareVolume, err := h.firmwareVolume()
	if err != nil {
		return HypervisorConfig{}, err
	}

	machineAccelerators := h.machineAccelerators()
	cpuFeatures := h.cpuFeatures()
	kernelParams := h.kernelParams()
	machineType := h.machineType()

	// The "microvm" machine type doesn't support NVDIMM so override the
	// config setting to explicitly disable it (i.e. don't require the
	// user to add 'disable_image_nvdimm = true' in the .toml file).
	if machineType == govmmQemu.MachineTypeMicrovm && !h.DisableImageNvdimm {
		h.DisableImageNvdimm = true
		kataUtilsLogger.Info("Setting 'disable_image_nvdimm = true' as microvm does not support NVDIMM")
	}

	// Nvdimm can only be support when UEFI/ACPI is enabled on arm64, otherwise disable it.
	if goruntime.GOARCH == "arm64" && firmware == "" {
		if p, err := h.PFlash(); err == nil {
			if len(p) == 0 {
				h.DisableImageNvdimm = true
				kataUtilsLogger.Info("Setting 'disable_image_nvdimm = true' if there is no firmware specified")
			}
		}
	}

	blockDriver, err := h.blockDeviceDriver()
	if err != nil {
		return HypervisorConfig{}, err
	}

	blockAIO, err := h.blockDeviceAIO()
	if err != nil {
		return HypervisorConfig{}, err
	}

	sharedFS, err := h.sharedFS()
	if err != nil {
		return HypervisorConfig{}, err
	}

	if (sharedFS == gt_config.VirtioFS || sharedFS == gt_config.VirtioFSNydus) && h.VirtioFSDaemon == "" {
		return HypervisorConfig{},
			fmt.Errorf("cannot enable %s without daemon path in configuration file", sharedFS)
	}

	if vSock, err := utils.SupportsVsocks(); !vSock {
		return HypervisorConfig{}, err
	}

	rxRateLimiterMaxRate := h.getRxRateLimiterCfg()
	txRateLimiterMaxRate := h.getTxRateLimiterCfg()

	extraMonitorSocket, err := h.extraMonitorSocket()
	if err != nil {
		return HypervisorConfig{}, err
	}

	return HypervisorConfig{
		HypervisorPath:           hypervisor,
		HypervisorPathList:       h.HypervisorPathList,
		KernelPath:               kernel,
		InitrdPath:               initrd,
		ImagePath:                image,
		RootfsType:               rootfsType,
		FirmwarePath:             firmware,
		FirmwareVolumePath:       firmwareVolume,
		PFlash:                   pflashes,
		MachineAccelerators:      machineAccelerators,
		CPUFeatures:              cpuFeatures,
		KernelParams:             DeserializeParams(vc.KernelParamFields(kernelParams)),
		HypervisorMachineType:    machineType,
		QgsPort:                  h.qgsPort(),
		NumVCPUsF:                h.defaultVCPUs(),
		DefaultMaxVCPUs:          h.defaultMaxVCPUs(),
		MemorySize:               h.defaultMemSz(),
		MemSlots:                 h.defaultMemSlots(),
		MemOffset:                h.defaultMemOffset(),
		DefaultMaxMemorySize:     h.defaultMaxMemSz(),
		VirtioMem:                h.VirtioMem,
		EntropySource:            h.GetEntropySource(),
		EntropySourceList:        h.EntropySourceList,
		DefaultBridges:           h.defaultBridges(),
		DisableBlockDeviceUse:    h.DisableBlockDeviceUse,
		SharedFS:                 sharedFS,
		VirtioFSDaemon:           h.VirtioFSDaemon,
		VirtioFSDaemonList:       h.VirtioFSDaemonList,
		HypervisorLoglevel:       h.defaultHypervisorLoglevel(),
		VirtioFSCacheSize:        h.VirtioFSCacheSize,
		VirtioFSCache:            h.defaultVirtioFSCache(),
		VirtioFSQueueSize:        h.VirtioFSQueueSize,
		VirtioFSExtraArgs:        h.VirtioFSExtraArgs,
		MemPrealloc:              h.MemPrealloc,
		HugePages:                h.HugePages,
		IOMMU:                    h.IOMMU,
		IOMMUPlatform:            h.getIOMMUPlatform(),
		FileBackedMemRootDir:     h.FileBackedMemRootDir,
		FileBackedMemRootList:    h.FileBackedMemRootList,
		Debug:                    h.Debug,
		DisableNestingChecks:     h.DisableNestingChecks,
		BlockDeviceDriver:        blockDriver,
		BlockDeviceAIO:           blockAIO,
		BlockDeviceCacheSet:      h.BlockDeviceCacheSet,
		BlockDeviceCacheDirect:   h.BlockDeviceCacheDirect,
		BlockDeviceCacheNoflush:  h.BlockDeviceCacheNoflush,
		EnableIOThreads:          h.EnableIOThreads,
		Msize9p:                  h.msize9p(),
		DisableImageNvdimm:       h.DisableImageNvdimm,
		HotPlugVFIO:              h.hotPlugVFIO(),
		ColdPlugVFIO:             h.coldPlugVFIO(),
		PCIeRootPort:             h.pcieRootPort(),
		PCIeSwitchPort:           h.pcieSwitchPort(),
		DisableVhostNet:          h.DisableVhostNet,
		EnableVhostUserStore:     h.EnableVhostUserStore,
		VhostUserStorePath:       h.vhostUserStorePath(),
		VhostUserStorePathList:   h.VhostUserStorePathList,
		VhostUserDeviceReconnect: h.VhostUserDeviceReconnect,
		SeccompSandbox:           h.SeccompSandbox,
		GuestHookPath:            h.guestHookPath(),
		RxRateLimiterMaxRate:     rxRateLimiterMaxRate,
		TxRateLimiterMaxRate:     txRateLimiterMaxRate,
		EnableAnnotations:        h.EnableAnnotations,
		GuestMemoryDumpPath:      h.GuestMemoryDumpPath,
		GuestMemoryDumpPaging:    h.GuestMemoryDumpPaging,
		ConfidentialGuest:        h.ConfidentialGuest,
		SevSnpGuest:              h.SevSnpGuest,
		GuestSwap:                h.GuestSwap,
		Rootless:                 h.Rootless,
		LegacySerial:             h.LegacySerial,
		DisableSeLinux:           h.DisableSeLinux,
		DisableGuestSeLinux:      h.DisableGuestSeLinux,
		ExtraMonitorSocket:       extraMonitorSocket,
		SnpIdBlock:               h.SnpIdBlock,
		SnpIdAuth:                h.SnpIdAuth,
	}, nil
}

func updateRuntimeConfigAgent(agentconf agent) (KataAgentConfig, error) {
	return KataAgentConfig {
		LongLiveConn:       true,
		Debug:              agentconf.debug(),
		Trace:              agentconf.trace(),
		KernelModules:      agentconf.kernelModules(),
		EnableDebugConsole: agentconf.debugConsoleEnabled(),
		DialTimeout:        agentconf.dialTimout(),
		CdhApiTimeout:      agentconf.cdhApiTimout(),
	}, nil
}

// ********** kata-containers\src\runtime\virtcontainers\qemu_arch_base.go **********
// A deeper PCIe topology than 5 is already not advisable just for the sake
// of having enough buffer we limit ourselves to 10 and exit if we reach
// the root bus
const maxPCIeTopoDepth = 10

type qemuArch interface {
	// enableNestingChecks nesting checks will be honoured
	enableNestingChecks()

	// disableNestingChecks nesting checks will be ignored
	disableNestingChecks()

	// runNested indicates if the hypervisor runs in a nested environment
	runNested() bool

	// enableVhostNet vhost will be enabled
	enableVhostNet()

	// disableVhostNet vhost will be disabled
	disableVhostNet()

	// machine returns the machine type
	machine() govmmQemu.Machine

	// qemuPath returns the path to the QEMU binary
	qemuPath() string

	// kernelParameters returns the kernel parameters
	// if debug is true then kernel debug parameters are included
	kernelParameters(debug bool) []Param

	//capabilities returns the capabilities supported by QEMU
	capabilities(config HypervisorConfig) types.Capabilities

	// bridges sets the number bridges for the machine type
	bridges(number uint32)

	// cpuTopology returns the CPU topology for the given amount of vcpus
	cpuTopology(vcpus, maxvcpus uint32) govmmQemu.SMP

	// cpuModel returns the CPU model for the machine type
	cpuModel() string

	// memoryTopology returns the memory topology using the given amount of memoryMb and hostMemoryMb
	memoryTopology(memoryMb, hostMemoryMb uint64, slots uint8) govmmQemu.Memory

	// protection returns platform protection
	getProtection() guestProtection

	// appendConsole appends a console to devices
	appendConsole(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error)

	// appendImage appends an image to devices
	appendImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error)

	// appendBlockImage appends an image as block device
	appendBlockImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error)

	// appendNvdimmImage appends an image as nvdimm device
	appendNvdimmImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error)

	// appendSCSIController appens a SCSI controller to devices
	appendSCSIController(devices []govmmQemu.Device, enableIOThreads bool) ([]govmmQemu.Device, *govmmQemu.IOThread, error)

	// appendBridges appends bridges to devices
	appendBridges(devices []govmmQemu.Device) []govmmQemu.Device

	// append9PVolume appends a 9P volume to devices
	append9PVolume(ctx context.Context, devices []govmmQemu.Device, volume types.Volume) ([]govmmQemu.Device, error)

	// appendSocket appends a socket to devices
	appendSocket(devices []govmmQemu.Device, socket types.Socket) []govmmQemu.Device

	// appendVSock appends a vsock PCI to devices
	appendVSock(ctx context.Context, devices []govmmQemu.Device, vsock types.VSock) ([]govmmQemu.Device, error)

	// appendNetwork appends a endpoint device to devices
	appendNetwork(ctx context.Context, devices []govmmQemu.Device, endpoint vc.Endpoint) ([]govmmQemu.Device, error)

	// appendBlockDevice appends a block drive to devices
	appendBlockDevice(devices []govmmQemu.Device, drive gt_config.BlockDrive) ([]govmmQemu.Device, error)

	// appendVhostUserDevice appends a vhost user device to devices
	appendVhostUserDevice(ctx context.Context, devices []govmmQemu.Device, drive gt_config.VhostUserDeviceAttrs) ([]govmmQemu.Device, error)

	// appendVFIODevice appends a VFIO device to devices
	appendVFIODevice(devices []govmmQemu.Device, vfioDevice gt_config.VFIODev) []govmmQemu.Device

	// appendRNGDevice appends a RNG device to devices
	appendRNGDevice(devices []govmmQemu.Device, rngDevice gt_config.RNGDev) ([]govmmQemu.Device, error)

	// setEndpointDevicePath sets the appropriate PCI or CCW device path for an endpoint
	setEndpointDevicePath(endpoint vc.Endpoint, bridgeAddr int, devAddr string) error

	// addDeviceToBridge adds devices to the bus
	addDeviceToBridge(ctx context.Context, ID string, t types.Type) (string, types.Bridge, error)

	// removeDeviceFromBridge removes devices to the bus
	removeDeviceFromBridge(ID string) error

	// getBridges grants access to Bridges
	getBridges() []types.Bridge

	// setBridges grants access to Bridges
	setBridges(bridges []types.Bridge)

	// addBridge adds a new Bridge to the list of Bridges
	addBridge(types.Bridge)

	// getPFlash() get pflash from configuration
	getPFlash() ([]string, error)

	// setPFlash() grants access to pflash
	setPFlash([]string)

	// handleImagePath handles the Hypervisor Config image path
	handleImagePath(config HypervisorConfig) error

	// supportGuestMemoryHotplug returns if the guest supports memory hotplug
	supportGuestMemoryHotplug() bool

	// setIgnoreSharedMemoryMigrationCaps set bypass-shared-memory capability for migration
	setIgnoreSharedMemoryMigrationCaps(context.Context, *govmmQemu.QMP) error

	// appendPCIeRootPortDevice appends a pcie-root-port device to pcie.0 bus
	appendPCIeRootPortDevice(devices []govmmQemu.Device, number uint32, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device

	// appendPCIeSwitch appends a ioh3420 device to a pcie-root-port
	appendPCIeSwitchPortDevice(devices []govmmQemu.Device, number uint32, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device

	// append vIOMMU device
	appendIOMMU(devices []govmmQemu.Device) ([]govmmQemu.Device, error)

	// append pvpanic device
	appendPVPanicDevice(devices []govmmQemu.Device) ([]govmmQemu.Device, error)

	// append protection device.
	// This implementation is architecture specific, some archs may need
	// a firmware, returns a string containing the path to the firmware that should
	// be used with the -bios option, ommit -bios option if the path is empty.
	appendProtectionDevice(devices []govmmQemu.Device, firmware, firmwareVolume string) ([]govmmQemu.Device, string, error)

	// scans the PCIe space and returns the biggest BAR sizes for 32-bit
	// and 64-bit addressable memory
	getBARsMaxAddressableMemory() (uint64, uint64)

	// Query QMP to find a device's PCI path given its QOM path or ID
	qomGetPciPath(qemuID string, qmpCh *qmpChannel) (types.PciPath, error)

	// Query QMP to find the PCI slot of a device, given its QOM path or ID
	qomGetSlot(qomPath string, qmpCh *qmpChannel) (types.PciSlot, error)
}

type qemuArchBase struct {
	qemuExePath          string
	qemuMachine          govmmQemu.Machine
	PFlash               []string
	kernelParamsNonDebug []Param
	kernelParamsDebug    []Param
	kernelParams         []Param
	Bridges              []types.Bridge
	memoryOffset         uint64
	networkIndex         int
	// Exclude from lint checking for it is ultimately only used in architecture-specific code
	protection    guestProtection //nolint:structcheck
	nestedRun     bool
	vhost         bool
	disableNvdimm bool
	dax           bool
	legacySerial  bool
}

const (
	defaultCores       uint32 = 1
	defaultThreads     uint32 = 1
	defaultCPUModel           = "host"
	defaultBridgeBus          = "pcie.0"
	defaultPCBridgeBus        = "pci.0"
	maxDevIDSize              = 31
	maxPCIeRootPort           = 16 // Limitation from QEMU
	maxPCIeSwitchPort         = 16 // Limitation from QEMU
)

// This is the PCI start address assigned to the first bridge that
// is added on the qemu command line. In case of x86_64, the first two PCI
// addresses (0 and 1) are used by the platform while in case of ARM, address
// 0 is reserved.
const bridgePCIStartAddr = 2

const (
	// QemuQ35 is the QEMU Q35 machine type for amd64
	QemuQ35 = "q35"

	// QemuMicrovm is the QEMU microvm machine type for amd64
	QemuMicrovm = "microvm"

	// QemuVirt is the QEMU virt machine type for aarch64 or amd64
	QemuVirt = "virt"

	// QemuPseries is a QEMU virt machine type for ppc64le
	QemuPseries = "pseries"

	// QemuCCWVirtio is a QEMU virt machine type for for s390x
	QemuCCWVirtio = "s390-ccw-virtio"

	qmpCapMigrationIgnoreShared = "x-ignore-shared"

	qemuNvdimmOption = "nvdimm=on"
)

// kernelParamsNonDebug is a list of the default kernel
// parameters that will be used in standard (non-debug) mode.
var kernelParamsNonDebug = []Param{
	{"quiet", ""},
}

// kernelParamsSystemdNonDebug is a list of the default systemd related
// kernel parameters that will be used in standard (non-debug) mode.
var kernelParamsSystemdNonDebug = []Param{
	{"systemd.show_status", "false"},
}

// kernelParamsDebug is a list of the default kernel
// parameters that will be used in debug mode (as much boot output as
// possible).
var kernelParamsDebug = []Param{
	{"debug", ""},
}

// kernelParamsSystemdDebug is a list of the default systemd related kernel
// parameters that will be used in debug mode (as much boot output as
// possible).
var kernelParamsSystemdDebug = []Param{
	{"systemd.show_status", "true"},
	{"systemd.log_level", "debug"},
}

// setup qemu arch
func (q *qemuArchBase) enableNestingChecks() {
	q.nestedRun = true
}

func (q *qemuArchBase) disableNestingChecks() {
	q.nestedRun = false
}

func (q *qemuArchBase) runNested() bool {
	return q.nestedRun
}

func (q *qemuArchBase) enableVhostNet() {
	q.vhost = true
}

func (q *qemuArchBase) disableVhostNet() {
	q.vhost = false
}

func (q *qemuArchBase) machine() govmmQemu.Machine {
	return q.qemuMachine
}

func (q *qemuArchBase) getProtection() guestProtection {
	return q.protection
}

func (q *qemuArchBase) qemuPath() string {
	return q.qemuExePath
}

func (q *qemuArchBase) kernelParameters(debug bool) []Param {
	params := q.kernelParams

	if debug {
		params = append(params, q.kernelParamsDebug...)
	} else {
		params = append(params, q.kernelParamsNonDebug...)
	}

	return params
}

func (q *qemuArchBase) capabilities(hConfig HypervisorConfig) types.Capabilities {
	var caps types.Capabilities
	caps.SetBlockDeviceHotplugSupport()
	caps.SetMultiQueueSupport()
	caps.SetNetworkDeviceHotplugSupported()
	if hConfig.SharedFS != gt_config.NoSharedFS {
		caps.SetFsSharingSupport()
	}
	return caps
}

func (q *qemuArchBase) bridges(number uint32) {
	for i := uint32(0); i < number; i++ {
		q.Bridges = append(q.Bridges, types.NewBridge(types.PCI, fmt.Sprintf("%s-bridge-%d", types.PCI, i), make(map[uint32]string), 0))
	}
}

func (q *qemuArchBase) cpuTopology(vcpus, maxvcpus uint32) govmmQemu.SMP {
	smp := govmmQemu.SMP{
		CPUs:    vcpus,
		Sockets: maxvcpus,
		Cores:   defaultCores,
		Threads: defaultThreads,
		MaxCPUs: maxvcpus,
	}

	return smp
}

func (q *qemuArchBase) cpuModel() string {
	return defaultCPUModel
}

func (q *qemuArchBase) memoryTopology(memoryMb, hostMemoryMb uint64, slots uint8) govmmQemu.Memory {
	memMax := fmt.Sprintf("%dM", hostMemoryMb)
	mem := fmt.Sprintf("%dM", memoryMb)
	memory := govmmQemu.Memory{
		Size:   mem,
		Slots:  slots,
		MaxMem: memMax,
	}

	return memory
}

func (q *qemuArchBase) appendConsole(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {
	var serial, console govmmQemu.Device
	var consoleKernelParams []Param

	if q.legacySerial {
		serial = govmmQemu.LegacySerialDevice{
			Chardev: "charconsole0",
		}

		console = govmmQemu.CharDevice{
			Driver:   govmmQemu.LegacySerial,
			Backend:  govmmQemu.Socket,
			DeviceID: "console0",
			ID:       "charconsole0",
			Path:     path,
		}

		consoleKernelParams = []Param{
			{"console", "ttyS0"},
		}
	} else {
		serial = govmmQemu.SerialDevice{
			Driver:        govmmQemu.VirtioSerial,
			ID:            "serial0",
			DisableModern: q.nestedRun,
			MaxPorts:      uint(2),
		}

		console = govmmQemu.CharDevice{
			Driver:   govmmQemu.Console,
			Backend:  govmmQemu.Socket,
			DeviceID: "console0",
			ID:       "charconsole0",
			Path:     path,
		}

		consoleKernelParams = []Param{
			{"console", "hvc0"},
			{"console", "hvc1"},
		}
	}

	devices = append(devices, serial)
	devices = append(devices, console)
	q.kernelParams = append(q.kernelParams, consoleKernelParams...)

	return devices, nil
}

func genericImage(path string) (gt_config.BlockDrive, error) {
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return gt_config.BlockDrive{}, err
	}

	randBytes, err := utils.GenerateRandomBytes(8)
	if err != nil {
		return gt_config.BlockDrive{}, err
	}

	id := utils.MakeNameID("image", hex.EncodeToString(randBytes), maxDevIDSize)

	drive := gt_config.BlockDrive{
		File:     path,
		Format:   "raw",
		ID:       id,
		ShareRW:  true,
		ReadOnly: true,
	}

	return drive, nil
}

func (q *qemuArchBase) appendNvdimmImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {
	imageFile, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer imageFile.Close()

	imageStat, err := imageFile.Stat()
	if err != nil {
		return nil, err
	}

	object := govmmQemu.Object{
		Driver:   govmmQemu.NVDIMM,
		Type:     govmmQemu.MemoryBackendFile,
		DeviceID: "nv0",
		ID:       "mem0",
		MemPath:  path,
		Size:     (uint64)(imageStat.Size()),
		ReadOnly: true,
	}

	devices = append(devices, object)

	return devices, nil
}

func (q *qemuArchBase) appendImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {
	return q.appendBlockImage(devices, path)
}

func (q *qemuArchBase) appendBlockImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {
	drive, err := genericImage(path)
	if err != nil {
		return nil, err
	}
	devices, err = q.appendBlockDevice(devices, drive)
	if err != nil {
		return nil, err
	}
	return devices, nil
}

func genericSCSIController(enableIOThreads, nestedRun bool) (govmmQemu.SCSIController, *govmmQemu.IOThread) {
	scsiController := govmmQemu.SCSIController{
		ID:            scsiControllerID,
		DisableModern: nestedRun,
	}

	var t *govmmQemu.IOThread

	if enableIOThreads {
		randBytes, _ := utils.GenerateRandomBytes(8)

		t = &govmmQemu.IOThread{
			ID: fmt.Sprintf("%s-%s", "iothread", hex.EncodeToString(randBytes)),
		}

		scsiController.IOThread = t.ID
	}

	return scsiController, t
}

func (q *qemuArchBase) appendSCSIController(devices []govmmQemu.Device, enableIOThreads bool) ([]govmmQemu.Device, *govmmQemu.IOThread, error) {
	d, t := genericSCSIController(enableIOThreads, q.nestedRun)
	devices = append(devices, d)
	return devices, t, nil
}

// appendBridges appends to devices the given bridges
func (q *qemuArchBase) appendBridges(devices []govmmQemu.Device) []govmmQemu.Device {
	return genericAppendBridges(devices, q.Bridges, q.qemuMachine.Type)
}

func generic9PVolume(volume types.Volume, nestedRun bool) govmmQemu.FSDevice {
	devID := fmt.Sprintf("extra-9p-%s", volume.MountTag)
	if len(devID) > maxDevIDSize {
		devID = devID[:maxDevIDSize]
	}

	return govmmQemu.FSDevice{
		Driver:        govmmQemu.Virtio9P,
		FSDriver:      govmmQemu.Local,
		ID:            devID,
		Path:          volume.HostPath,
		MountTag:      volume.MountTag,
		SecurityModel: govmmQemu.None,
		DisableModern: nestedRun,
		Multidev:      govmmQemu.Remap,
	}
}

func genericAppend9PVolume(devices []govmmQemu.Device, volume types.Volume, nestedRun bool) (govmmQemu.FSDevice, error) {
	d := generic9PVolume(volume, nestedRun)
	return d, nil
}

func (q *qemuArchBase) append9PVolume(_ context.Context, devices []govmmQemu.Device, volume types.Volume) ([]govmmQemu.Device, error) {
	if volume.MountTag == "" || volume.HostPath == "" {
		return devices, nil
	}

	d, err := genericAppend9PVolume(devices, volume, q.nestedRun)
	if err != nil {
		return nil, err
	}

	devices = append(devices, d)
	return devices, nil
}

func (q *qemuArchBase) appendSocket(devices []govmmQemu.Device, socket types.Socket) []govmmQemu.Device {
	devID := socket.ID
	if len(devID) > maxDevIDSize {
		devID = devID[:maxDevIDSize]
	}

	devices = append(devices,
		govmmQemu.CharDevice{
			Driver:   govmmQemu.VirtioSerialPort,
			Backend:  govmmQemu.Socket,
			DeviceID: socket.DeviceID,
			ID:       devID,
			Path:     socket.HostPath,
			Name:     socket.Name,
		},
	)

	return devices
}

func (q *qemuArchBase) appendVSock(_ context.Context, devices []govmmQemu.Device, vsock types.VSock) ([]govmmQemu.Device, error) {
	devices = append(devices,
		govmmQemu.VSOCKDevice{
			ID:            fmt.Sprintf("vsock-%d", vsock.ContextID),
			ContextID:     vsock.ContextID,
			VHostFD:       vsock.VhostFd,
			DisableModern: q.nestedRun,
		},
	)

	return devices, nil

}

func networkModelToQemuType(model vc.NetInterworkingModel) govmmQemu.NetDeviceType {
	switch model {
	case vc.NetXConnectMacVtapModel:
		return govmmQemu.MACVTAP
	default:
		//TAP should work for most other cases
		return govmmQemu.TAP
	}
}

func genericNetwork(endpoint vc.Endpoint, vhost, nestedRun bool, index int) (govmmQemu.NetDevice, error) {
	var d govmmQemu.NetDevice
	switch ep := endpoint.(type) {
	case *vc.VethEndpoint, *vc.MacvlanEndpoint, *vc.IPVlanEndpoint:
		netPair := ep.NetworkPair()
		d = govmmQemu.NetDevice{
			Type:          networkModelToQemuType(netPair.NetInterworkingModel),
			Driver:        govmmQemu.VirtioNet,
			ID:            fmt.Sprintf("network-%d", index),
			IFName:        netPair.TAPIface.Name,
			MACAddress:    netPair.TAPIface.HardAddr,
			DownScript:    "no",
			Script:        "no",
			VHost:         vhost,
			DisableModern: nestedRun,
			FDs:           netPair.VMFds,
			VhostFDs:      netPair.VhostFds,
		}
	case *vc.MacvtapEndpoint:
		d = govmmQemu.NetDevice{
			Type:          govmmQemu.MACVTAP,
			Driver:        govmmQemu.VirtioNet,
			ID:            fmt.Sprintf("network-%d", index),
			IFName:        ep.Name(),
			MACAddress:    ep.HardwareAddr(),
			DownScript:    "no",
			Script:        "no",
			VHost:         vhost,
			DisableModern: nestedRun,
			FDs:           ep.VMFds,
			VhostFDs:      ep.VhostFds,
		}
	case *vc.TuntapEndpoint:
		netPair := ep.NetworkPair()
		d = govmmQemu.NetDevice{
			Type:          govmmQemu.NetDeviceType("tap"),
			Driver:        govmmQemu.VirtioNet,
			ID:            fmt.Sprintf("network-%d", index),
			IFName:        netPair.TAPIface.Name,
			MACAddress:    netPair.TAPIface.HardAddr,
			DownScript:    "no",
			Script:        "no",
			VHost:         vhost,
			DisableModern: nestedRun,
			FDs:           netPair.VMFds,
			VhostFDs:      netPair.VhostFds,
		}
	default:
		return govmmQemu.NetDevice{}, fmt.Errorf("Unknown type for endpoint")
	}

	return d, nil
}

func (q *qemuArchBase) appendNetwork(_ context.Context, devices []govmmQemu.Device, endpoint vc.Endpoint) ([]govmmQemu.Device, error) {
	d, err := genericNetwork(endpoint, q.vhost, q.nestedRun, q.networkIndex)
	if err != nil {
		return devices, fmt.Errorf("Failed to append network %v", err)
	}
	q.networkIndex++
	devices = append(devices, d)
	return devices, nil
}

func genericBlockDevice(drive gt_config.BlockDrive, nestedRun bool) (govmmQemu.BlockDevice, error) {
	if drive.File == "" || drive.ID == "" || drive.Format == "" {
		return govmmQemu.BlockDevice{}, fmt.Errorf("Empty File, ID or Format for drive %v", drive)
	}

	if len(drive.ID) > maxDevIDSize {
		drive.ID = drive.ID[:maxDevIDSize]
	}

	return govmmQemu.BlockDevice{
		Driver:        govmmQemu.VirtioBlock,
		ID:            drive.ID,
		File:          drive.File,
		AIO:           govmmQemu.Threads,
		Format:        govmmQemu.BlockDeviceFormat(drive.Format),
		Interface:     "none",
		DisableModern: nestedRun,
		ShareRW:       drive.ShareRW,
		ReadOnly:      drive.ReadOnly,
	}, nil
}

func (q *qemuArchBase) appendBlockDevice(devices []govmmQemu.Device, drive gt_config.BlockDrive) ([]govmmQemu.Device, error) {
	d, err := genericBlockDevice(drive, q.nestedRun)
	if err != nil {
		return devices, fmt.Errorf("Failed to append block device %v", err)
	}
	devices = append(devices, d)
	return devices, nil
}

func (q *qemuArchBase) appendVhostUserDevice(ctx context.Context, devices []govmmQemu.Device, attr gt_config.VhostUserDeviceAttrs) ([]govmmQemu.Device, error) {
	qemuVhostUserDevice := govmmQemu.VhostUserDevice{}

	switch attr.Type {
	case gt_config.VhostUserNet:
		qemuVhostUserDevice.TypeDevID = utils.MakeNameID("net", attr.DevID, maxDevIDSize)
		qemuVhostUserDevice.Address = attr.MacAddress
		qemuVhostUserDevice.VhostUserType = govmmQemu.VhostUserNet
	case gt_config.VhostUserSCSI:
		qemuVhostUserDevice.TypeDevID = utils.MakeNameID("scsi", attr.DevID, maxDevIDSize)
		qemuVhostUserDevice.VhostUserType = govmmQemu.VhostUserSCSI
	case gt_config.VhostUserBlk:
		qemuVhostUserDevice.VhostUserType = govmmQemu.VhostUserBlk
	case gt_config.VhostUserFS:
		qemuVhostUserDevice.TypeDevID = utils.MakeNameID("fs", attr.DevID, maxDevIDSize)
		qemuVhostUserDevice.Tag = attr.Tag
		qemuVhostUserDevice.CacheSize = attr.CacheSize
		qemuVhostUserDevice.QueueSize = attr.QueueSize
		qemuVhostUserDevice.VhostUserType = govmmQemu.VhostUserFS
	}

	qemuVhostUserDevice.SocketPath = attr.SocketPath
	qemuVhostUserDevice.CharDevID = utils.MakeNameID("char", attr.DevID, maxDevIDSize)

	devices = append(devices, qemuVhostUserDevice)

	return devices, nil
}

func (q *qemuArchBase) appendVFIODevice(devices []govmmQemu.Device, vfioDev gt_config.VFIODev) []govmmQemu.Device {

	if vfioDev.BDF == "" {
		return devices
	}

	devices = append(devices,
		govmmQemu.VFIODevice{
			ID:       vfioDev.ID,
			BDF:      vfioDev.BDF,
			VendorID: vfioDev.VendorID,
			DeviceID: vfioDev.DeviceID,
			Bus:      vfioDev.Bus,
			SysfsDev: vfioDev.SysfsDev,
			DevfsDev: vfioDev.DevfsDev,
		},
	)

	return devices
}

func (q *qemuArchBase) appendRNGDevice(devices []govmmQemu.Device, rngDev gt_config.RNGDev) ([]govmmQemu.Device, error) {
	devices = append(devices,
		govmmQemu.RngDevice{
			ID:       rngDev.ID,
			Filename: rngDev.Filename,
		},
	)

	return devices, nil
}

func (q *qemuArchBase) setEndpointDevicePath(endpoint vc.Endpoint, bridgeAddr int, devAddr string) error {
	bridgeSlot, err := types.PciSlotFromInt(bridgeAddr)
	if err != nil {
		return err
	}
	devSlot, err := types.PciSlotFromString(devAddr)
	if err != nil {
		return err
	}
	pciPath, err := types.PciPathFromSlots(bridgeSlot, devSlot)
	if err != nil {
		return err
	}
	endpoint.SetPciPath(pciPath)
	return nil
}

func (q *qemuArchBase) handleImagePath(config HypervisorConfig) error {
	if config.ImagePath != "" {
		kernelRootParams, err := GetKernelRootParams(config.RootfsType, q.disableNvdimm, false)
		if err != nil {
			return err
		}
		if !q.disableNvdimm {
			q.qemuMachine.Options = strings.Join([]string{
				q.qemuMachine.Options, qemuNvdimmOption,
			}, ",")
			kernelRootParams, err = GetKernelRootParams(config.RootfsType, q.disableNvdimm, q.dax)
			if err != nil {
				return err
			}
		}
		q.kernelParams = append(q.kernelParams, kernelRootParams...)
		q.kernelParamsNonDebug = append(q.kernelParamsNonDebug, kernelParamsSystemdNonDebug...)
		q.kernelParamsDebug = append(q.kernelParamsDebug, kernelParamsSystemdDebug...)
	}

	return nil
}

func (q *qemuArchBase) supportGuestMemoryHotplug() bool {
	return q.protection == noneProtection
}

func (q *qemuArchBase) setIgnoreSharedMemoryMigrationCaps(ctx context.Context, qmp *govmmQemu.QMP) error {
	err := qmp.ExecSetMigrationCaps(ctx, []map[string]interface{}{
		{
			"capability": qmpCapMigrationIgnoreShared,
			"state":      true,
		},
	})
	return err
}

func (q *qemuArchBase) addDeviceToBridge(ctx context.Context, ID string, t types.Type) (string, types.Bridge, error) {
	addr, b, err := genericAddDeviceToBridge(ctx, q.Bridges, ID, t)
	if err != nil {
		return "", b, err
	}

	return fmt.Sprintf("%02x", addr), b, nil
}

func genericAddDeviceToBridge(ctx context.Context, bridges []types.Bridge, ID string, t types.Type) (uint32, types.Bridge, error) {
	var err error
	var addr uint32

	if len(bridges) == 0 {
		return 0, types.Bridge{}, errors.New("failed to get available address from bridges")
	}

	// looking for an empty address in the bridges
	for _, b := range bridges {
		if t != b.Type {
			continue
		}
		addr, err = b.AddDevice(ctx, ID)
		if err == nil {
			return addr, b, nil
		}
	}

	return 0, types.Bridge{}, fmt.Errorf("no more bridge slots available")
}

func (q *qemuArchBase) removeDeviceFromBridge(ID string) error {
	var err error
	for _, b := range q.Bridges {
		err = b.RemoveDevice(ID)
		if err == nil {
			// device was removed correctly
			return nil
		}
	}

	return err
}

func (q *qemuArchBase) getBridges() []types.Bridge {
	return q.Bridges
}

func (q *qemuArchBase) setBridges(bridges []types.Bridge) {
	q.Bridges = bridges
}

func (q *qemuArchBase) addBridge(b types.Bridge) {
	q.Bridges = append(q.Bridges, b)
}

// appendPCIeRootPortDevice appends to devices the given pcie-root-port
func (q *qemuArchBase) appendPCIeRootPortDevice(devices []govmmQemu.Device, number uint32, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device {
	return genericAppendPCIeRootPort(devices, number, q.qemuMachine.Type, memSize32bit, memSize64bit)
}

// appendPCIeSwitchPortDevice appends a PCIe Switch with <number> ports
func (q *qemuArchBase) appendPCIeSwitchPortDevice(devices []govmmQemu.Device, number uint32, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device {
	return genericAppendPCIeSwitchPort(devices, number, q.qemuMachine.Type, memSize32bit, memSize64bit)
}

// getBARsMaxAddressableMemory we need to know the BAR sizes to configure the
// PCIe Root Port or PCIe Downstream Port attaching a device with huge BARs.
func (q *qemuArchBase) getBARsMaxAddressableMemory() (uint64, uint64) {

	pci := nvpci.New()
	devs, _ := pci.GetAllDevices()

	// Since we do not know which devices are going to be hotplugged,
	// we're going to use the GPU with the biggest BARs to initialize the
	// root port, this should work for all other devices as well.
	// defaults are 2MB for both, if no suitable devices found
	max32bit := uint64(2 * 1024 * 1024)
	max64bit := uint64(2 * 1024 * 1024)

	for _, dev := range devs {
		if !dev.IsGPU() {
			continue
		}
		memSize32bit, memSize64bit := dev.Resources.GetTotalAddressableMemory(true)
		if max32bit < memSize32bit {
			max32bit = memSize32bit
		}
		if max64bit < memSize64bit {
			max64bit = memSize64bit
		}
	}
	// The actual 32bit is most of the time a power of 2 but we need some
	// buffer so double that to leave space for other IO functions.
	// The 64bit size is not a power of 2 and hence is already rounded up
	// to the higher value.
	return max32bit * 2, max64bit
}

// appendIOMMU appends a virtual IOMMU device
func (q *qemuArchBase) appendIOMMU(devices []govmmQemu.Device) ([]govmmQemu.Device, error) {
	switch q.qemuMachine.Type {
	case QemuQ35:
		iommu := govmmQemu.IommuDev{
			Intremap:    true,
			DeviceIotlb: true,
			CachingMode: true,
		}

		devices = append(devices, iommu)
		return devices, nil
	default:
		return devices, fmt.Errorf("Machine Type %s does not support vIOMMU", q.qemuMachine.Type)
	}
}

// appendPVPanicDevice appends a pvpanic device
func (q *qemuArchBase) appendPVPanicDevice(devices []govmmQemu.Device) ([]govmmQemu.Device, error) {
	devices = append(devices, govmmQemu.PVPanicDevice{NoShutdown: true})
	return devices, nil
}

func (q *qemuArchBase) getPFlash() ([]string, error) {
	return q.PFlash, nil
}

func (q *qemuArchBase) setPFlash(p []string) {
	q.PFlash = p
}

// Query QMP to find the PCI slot of a device, given its QOM path or ID
func (q *qemuArchBase) qomGetSlot(qomPath string, qmpCh *qmpChannel) (types.PciSlot, error) {
	addr, err := qmpCh.qmp.ExecQomGet(qmpCh.ctx, qomPath, "addr")
	if err != nil {
		return types.PciSlot{}, err
	}
	addrf, ok := addr.(float64)
	// XXX going via float makes no real sense, but that's how
	// JSON works, and we'll get away with it for the small values
	// we have here
	if !ok {
		return types.PciSlot{}, fmt.Errorf("addr QOM property of %q is %T not a number", qomPath, addr)
	}
	addri := int(addrf)

	slotNum, funcNum := addri>>3, addri&0x7
	if funcNum != 0 {
		return types.PciSlot{}, fmt.Errorf("Unexpected non-zero PCI function (%02x.%1x) on %q",
			slotNum, funcNum, qomPath)
	}

	return types.PciSlotFromInt(slotNum)
}

// Query QMP to find a device's PCI path given its QOM path or ID
func (q *qemuArchBase) qomGetPciPath(qemuID string, qmpCh *qmpChannel) (types.PciPath, error) {

	var slots []types.PciSlot

	devSlot, err := q.qomGetSlot(qemuID, qmpCh)
	if err != nil {
		return types.PciPath{}, err
	}
	slots = append(slots, devSlot)

	// This only works for Q35 and Virt
	r, _ := regexp.Compile(`^/machine/.*/pcie.0`)

	var parentPath = qemuID
	// We do not want to use a forever loop here, a deeper PCIe topology
	// than 5 is already not advisable just for the sake of having enough
	// buffer we limit ourselves to 10 and leave the loop early if we hit
	// the root bus.
	for i := 1; i <= maxPCIeTopoDepth; i++ {
		parenBusQOM, err := qmpCh.qmp.ExecQomGet(qmpCh.ctx, parentPath, "parent_bus")
		if err != nil {
			return types.PciPath{}, err
		}

		busQOM, ok := parenBusQOM.(string)
		if !ok {
			return types.PciPath{}, fmt.Errorf("parent_bus QOM property of %s is %t not a string", qemuID, parenBusQOM)
		}

		// If we hit /machine/q35/pcie.0 we're done this is the root bus
		// we climbed the complete hierarchy
		if r.Match([]byte(busQOM)) {
			break
		}

		// `bus` is the QOM path of the QOM bus object, but we need
		// the PCI parent_bus which manages that bus.  There doesn't seem
		// to be a way to get that other than to simply drop the last
		// path component.
		idx := strings.LastIndex(busQOM, "/")
		if idx == -1 {
			return types.PciPath{}, fmt.Errorf("Bus has unexpected QOM path %s", busQOM)
		}
		parentBus := busQOM[:idx]

		parentSlot, err := q.qomGetSlot(parentBus, qmpCh)
		if err != nil {
			return types.PciPath{}, err
		}

		// Prepend the slots, since we're climbing the hierarchy
		slots = append([]types.PciSlot{parentSlot}, slots...)
		parentPath = parentBus
	}
	return types.PciPathFromSlots(slots...)
}


// ********** kata-containers\src\runtime\virtcontainers\hypervisor.go **********
// Param is a key/value representation for hypervisor and kernel parameters.
type Param struct {
	Key   string
	Value string
}

// HypervisorConfig is the hypervisor configuration.
// nolint: govet
type HypervisorConfig struct {
	// customAssets is a map of assets.
	// Each value in that map takes precedence over the configured assets.
	// For example, if there is a value for the "kernel" key in this map,
	// it will be used for the sandbox's kernel path instead of KernelPath.
	customAssets map[types.AssetType]*types.Asset

	// Supplementary group IDs.
	Groups []uint32

	// KernelPath is the guest kernel host path.
	KernelPath string

	// ImagePath is the guest image host path.
	ImagePath string

	// InitrdPath is the guest initrd image host path.
	// ImagePath and InitrdPath cannot be set at the same time.
	InitrdPath string

	// RootfsType is filesystem type of rootfs.
	RootfsType string

	// FirmwarePath is the bios host path
	FirmwarePath string

	// FirmwareVolumePath is the configuration volume path for the firmware
	FirmwareVolumePath string

	// MachineAccelerators are machine specific accelerators
	MachineAccelerators string

	// CPUFeatures are cpu specific features
	CPUFeatures string

	// HypervisorPath is the hypervisor executable host path.
	HypervisorPath string

	// HypervisorCtlPath is the hypervisor ctl executable host path.
	HypervisorCtlPath string

	// JailerPath is the jailer executable host path.
	JailerPath string

	// BlockDeviceDriver specifies the driver to be used for block device
	// either VirtioSCSI or VirtioBlock with the default driver being defaultBlockDriver
	BlockDeviceDriver string

	// HypervisorMachineType specifies the type of machine being
	// emulated.
	HypervisorMachineType string

	// MemoryPath is the memory file path of VM memory. Used when either BootToBeTemplate or
	// BootFromTemplate is true.
	MemoryPath string

	// DevicesStatePath is the VM device state file path. Used when either BootToBeTemplate or
	// BootFromTemplate is true.
	DevicesStatePath string

	// EntropySource is the path to a host source of
	// entropy (/dev/random, /dev/urandom or real hardware RNG device)
	EntropySource string

	// Shared file system type:
	//   - virtio-9p
	//   - virtio-fs (default)
	SharedFS string

	// Path for filesystem sharing
	SharedPath string

	// VirtioFSDaemon is the virtio-fs vhost-user daemon path
	VirtioFSDaemon string

	// VirtioFSCache cache mode for fs version cache
	VirtioFSCache string

	// File based memory backend root directory
	FileBackedMemRootDir string

	// VhostUserStorePath is the directory path where vhost-user devices
	// related folders, sockets and device nodes should be.
	VhostUserStorePath string

	// VhostUserDeviceReconnect is the timeout for reconnecting on non-server spdk sockets
	// when the remote end goes away. Zero disables reconnecting.
	VhostUserDeviceReconnect uint32

	// GuestCoredumpPath is the path in host for saving guest memory dump
	GuestMemoryDumpPath string

	// GuestHookPath is the path within the VM that will be used for 'drop-in' hooks
	GuestHookPath string

	// VMid is the id of the VM that create the hypervisor if the VM is created by the factory.
	// VMid is "" if the hypervisor is not created by the factory.
	VMid string

	// VMStorePath is the location on disk where VM information will persist
	VMStorePath string

	// VMStorePath is the location on disk where runtime information will persist
	RunStorePath string

	// SELinux label for the VM
	SELinuxProcessLabel string

	// HypervisorPathList is the list of hypervisor paths names allowed in annotations
	HypervisorPathList []string

	// JailerPathList is the list of jailer paths names allowed in annotations
	JailerPathList []string

	// EntropySourceList is the list of valid entropy sources
	EntropySourceList []string

	// VirtioFSDaemonList is the list of valid virtiofs names for annotations
	VirtioFSDaemonList []string

	// VirtioFSExtraArgs passes options to virtiofsd daemon
	VirtioFSExtraArgs []string

	// Enable annotations by name
	EnableAnnotations []string

	// FileBackedMemRootList is the list of valid root directories values for annotations
	FileBackedMemRootList []string

	// PFlash image paths
	PFlash []string

	// VhostUserStorePathList is the list of valid values for vhost-user paths
	VhostUserStorePathList []string

	// SeccompSandbox is the qemu function which enables the seccomp feature
	SeccompSandbox string

	// BlockiDeviceAIO specifies the I/O API to be used.
	BlockDeviceAIO string

	// The socket to connect to the remote hypervisor implementation on
	RemoteHypervisorSocket string

	// The name of the sandbox (pod)
	SandboxName string

	// The name of the namespace of the sandbox (pod)
	SandboxNamespace string

	// The user maps to the uid.
	User string

	// SnpIdBlock is the 96-byte, base64-encoded blob to provide the ID Block structure
	// for the SNP_LAUNCH_FINISH command defined in the SEV-SNP firmware ABI (default: all-zero)
	SnpIdBlock string

	// SnpIdAuth is the 4096-byte, base64-encoded blob to provide the ID Authentication Information Structure
	// for the SNP_LAUNCH_FINISH command defined in the SEV-SNP firmware ABI (default: all-zero)
	SnpIdAuth string

	// KernelParams are additional guest kernel parameters.
	KernelParams []Param

	// HypervisorParams are additional hypervisor parameters.
	HypervisorParams []Param

	// SGXEPCSize specifies the size in bytes for the EPC Section.
	// Enable SGX. Hardware-based isolation and memory encryption.
	SGXEPCSize int64

	// DiskRateLimiterBwRate is used to control disk I/O bandwidth on VM level.
	// The same value, defined in bits per second, is used for inbound and outbound bandwidth.
	DiskRateLimiterBwMaxRate int64

	// DiskRateLimiterBwOneTimeBurst is used to control disk I/O bandwidth on VM level.
	// This increases the initial max rate and this initial extra credit does *NOT* replenish
	// and can be used for an *initial* burst of data.
	DiskRateLimiterBwOneTimeBurst int64

	// DiskRateLimiterOpsRate is used to control disk I/O operations on VM level.
	// The same value, defined in operations per second, is used for inbound and outbound bandwidth.
	DiskRateLimiterOpsMaxRate int64

	// DiskRateLimiterOpsOneTimeBurst is used to control disk I/O operations on VM level.
	// This increases the initial max rate and this initial extra credit does *NOT* replenish
	// and can be used for an *initial* burst of data.
	DiskRateLimiterOpsOneTimeBurst int64

	// RxRateLimiterMaxRate is used to control network I/O inbound bandwidth on VM level.
	RxRateLimiterMaxRate uint64

	// TxRateLimiterMaxRate is used to control network I/O outbound bandwidth on VM level.
	TxRateLimiterMaxRate uint64

	// NetRateLimiterBwRate is used to control network I/O bandwidth on VM level.
	// The same value, defined in bits per second, is used for inbound and outbound bandwidth.
	NetRateLimiterBwMaxRate int64

	// NetRateLimiterBwOneTimeBurst is used to control network I/O bandwidth on VM level.
	// This increases the initial max rate and this initial extra credit does *NOT* replenish
	// and can be used for an *initial* burst of data.
	NetRateLimiterBwOneTimeBurst int64

	// NetRateLimiterOpsRate is used to control network I/O operations on VM level.
	// The same value, defined in operations per second, is used for inbound and outbound bandwidth.
	NetRateLimiterOpsMaxRate int64

	// NetRateLimiterOpsOneTimeBurst is used to control network I/O operations on VM level.
	// This increases the initial max rate and this initial extra credit does *NOT* replenish
	// and can be used for an *initial* burst of data.
	NetRateLimiterOpsOneTimeBurst int64

	// MemOffset specifies memory space for nvdimm device
	MemOffset uint64

	// VFIODevices are used to get PCIe device info early before the sandbox
	// is started to make better PCIe topology decisions
	VFIODevices []gt_config.DeviceInfo
	// VhostUserBlkDevices are handled differently in Q35 and Virt machine
	// type. capture them early before the sandbox to make better PCIe topology
	// decisions
	VhostUserBlkDevices []gt_config.DeviceInfo

	// HotplugVFIO is used to indicate if devices need to be hotplugged on the
	// root port or a switch
	HotPlugVFIO gt_config.PCIePort

	// ColdPlugVFIO is used to indicate if devices need to be coldplugged on the
	// root port, switch or no port
	ColdPlugVFIO gt_config.PCIePort

	// PCIeRootPort is the number of root-port to create for the VM
	PCIeRootPort uint32

	// PCIeSwitchPort is the number of switch-port to create for the VM
	PCIeSwitchPort uint32

	// NumVCPUs specifies default number of vCPUs for the VM.
	NumVCPUsF float32

	//DefaultMaxVCPUs specifies the maximum number of vCPUs for the VM.
	DefaultMaxVCPUs uint32

	// DefaultMem specifies default memory size in MiB for the VM.
	MemorySize uint32

	// DefaultMaxMemorySize specifies the maximum amount of RAM in MiB for the VM.
	DefaultMaxMemorySize uint64

	// DefaultBridges specifies default number of bridges for the VM.
	// Bridges can be used to hot plug devices
	DefaultBridges uint32

	// Msize9p is used as the msize for 9p shares
	Msize9p uint32

	// MemSlots specifies default memory slots the VM.
	MemSlots uint32

	// VirtioFSCacheSize is the DAX cache size in MiB
	VirtioFSCacheSize uint32

	// Size of virtqueues
	VirtioFSQueueSize uint32

	// User ID.
	Uid uint32

	// Group ID.
	Gid uint32

	// Timeout for actions e.g. startVM for the remote hypervisor
	RemoteHypervisorTimeout uint32

	// BlockDeviceCacheSet specifies cache-related options will be set to block devices or not.
	BlockDeviceCacheSet bool

	// BlockDeviceCacheDirect specifies cache-related options for block devices.
	// Denotes whether use of O_DIRECT (bypass the host page cache) is enabled.
	BlockDeviceCacheDirect bool

	// BlockDeviceCacheNoflush specifies cache-related options for block devices.
	// Denotes whether flush requests for the device are ignored.
	BlockDeviceCacheNoflush bool

	// DisableBlockDeviceUse disallows a block device from being used.
	DisableBlockDeviceUse bool

	// EnableIOThreads enables IO to be processed in a separate thread.
	// Supported currently for virtio-scsi driver.
	EnableIOThreads bool

	// Debug changes the default hypervisor and kernel parameters to
	// enable debug output where available.
	Debug bool

	// HypervisorLoglevel determines the level of logging emitted
	// from the hypervisor. Accepts values 0-3.
	HypervisorLoglevel uint32

	// MemPrealloc specifies if the memory should be pre-allocated
	MemPrealloc bool

	// HugePages specifies if the memory should be pre-allocated from huge pages
	HugePages bool

	// VirtioMem is used to enable/disable virtio-mem
	VirtioMem bool

	// IOMMU specifies if the VM should have a vIOMMU
	IOMMU bool

	// IOMMUPlatform is used to indicate if IOMMU_PLATFORM is enabled for supported devices
	IOMMUPlatform bool

	// DisableNestingChecks is used to override customizations performed
	// when running on top of another VMM.
	DisableNestingChecks bool

	// DisableImageNvdimm is used to disable guest rootfs image nvdimm devices
	DisableImageNvdimm bool

	// GuestMemoryDumpPaging is used to indicate if enable paging
	// for QEMU dump-guest-memory command
	GuestMemoryDumpPaging bool

	// Enable confidential guest support.
	// Enable or disable different hardware features, ranging
	// from memory encryption to both memory and CPU-state encryption and integrity.
	ConfidentialGuest bool

	// Enable SEV-SNP guests on AMD machines capable of both
	SevSnpGuest bool

	// BootToBeTemplate used to indicate if the VM is created to be a template VM
	BootToBeTemplate bool

	// BootFromTemplate used to indicate if the VM should be created from a template VM
	BootFromTemplate bool

	// DisableVhostNet is used to indicate if host supports vhost_net
	DisableVhostNet bool

	// EnableVhostUserStore is used to indicate if host supports vhost-user-blk/scsi
	EnableVhostUserStore bool

	// GuestSwap Used to enable/disable swap in the guest
	GuestSwap bool

	// Rootless is used to enable rootless VMM process
	Rootless bool

	// Disable seccomp from the hypervisor process
	DisableSeccomp bool

	// Disable selinux from the hypervisor process
	DisableSeLinux bool

	// Disable selinux from the container process
	DisableGuestSeLinux bool

	// Use legacy serial for the guest console
	LegacySerial bool

	// ExtraMonitorSocket allows to add an extra HMP or QMP socket when the VMM is Qemu
	ExtraMonitorSocket govmmQemu.MonitorProtocol

	// QgsPort defines Intel Quote Generation Service port exposed from the host
	QgsPort uint32

	// Initdata defines the initdata passed into guest when CreateVM
	Initdata string

	// GPU specific annotations (currently only applicable for Remote Hypervisor)
	//DefaultGPUs specifies the number of GPUs required for the Kata VM
	DefaultGPUs uint32
	// DefaultGPUModel specifies GPU model like tesla, h100, readeon etc.
	DefaultGPUModel string
}

// Kind of guest protection
type guestProtection uint8

const (
	noneProtection guestProtection = iota

	//Intel Trust Domain Extensions
	//https://software.intel.com/content/www/us/en/develop/articles/intel-trust-domain-extensions.html
	// Exclude from lint checking for it won't be used on arm64 code
	tdxProtection

	// AMD Secure Encrypted Virtualization
	// https://developer.amd.com/sev/
	// Exclude from lint checking for it won't be used on arm64 code
	sevProtection

	// AMD Secure Encrypted Virtualization - Secure Nested Paging (SEV-SNP)
	// https://developer.amd.com/sev/
	// Exclude from lint checking for it won't be used on arm64 code
	snpProtection

	// IBM POWER 9 Protected Execution Facility
	// https://www.kernel.org/doc/html/latest/powerpc/ultravisor.html
	// Exclude from lint checking for it won't be used on arm64 code
	pefProtection

	// IBM Secure Execution (IBM Z & LinuxONE)
	// https://www.kernel.org/doc/html/latest/virt/kvm/s390-pv.html
	// Exclude from lint checking for it won't be used on arm64 code
	seProtection

	// virtCCA, a mature virtualized ARM CCA available on existing ARM platforms
	// https://arxiv.org/abs/2306.11011
	virtccaProtection
)

var guestProtectionStr = [...]string{
	noneProtection: "none",
	pefProtection:  "pef",
	seProtection:   "se",
	sevProtection:  "sev",
	snpProtection:  "snp",
	tdxProtection:  "tdx",
	virtccaProtection:  "virtcca",
}

func (gp guestProtection) String() string {
	return guestProtectionStr[gp]
}

func availableGuestProtection() (guestProtection, error) {
	return virtccaProtection, nil
}

func genericAvailableGuestProtections() (protections []string) {
	return
}

func AvailableGuestProtections() (protections []string) {
	gp, err := availableGuestProtection()
	if err != nil || gp == noneProtection {
		return genericAvailableGuestProtections()
	}
	return []string{gp.String()}
}

const defaultQemuPath = "/usr/bin/qemu-system-aarch64"

const defaultQemuMachineType = QemuVirt

const qmpMigrationWaitTimeout = 10 * time.Second

const defaultQemuMachineOptions = "usb=off,accel=kvm,gic-version=host"
const defaultCVMQemuMachineOptions = "gic-version=3,accel=kvm,kernel_irqchip=on"

var kernelParams = []Param{
	{"iommu.passthrough", "0"},
}

var cvmkernelParams = []Param{
	{"iommu.passthrough", "0"},
	{"console", "tty0"},
	{"console", "ttyAMA0"},
	{"kaslr.disabled", "1"},
	{"rodata", "off"},
	{"cvm_guest", "1"},
}

var supportedQemuMachine = govmmQemu.Machine{
	Type:    QemuVirt,
	Options: defaultQemuMachineOptions,
}

var supportedCVMQemuMachine = govmmQemu.Machine{
	Type:    QemuVirt,
	Options: defaultCVMQemuMachineOptions,
}

type qemuArm64 struct {
	// inherit from qemuArchBase, overwrite methods if needed
	qemuArchBase
}

func newQemuArch(config HypervisorConfig) (qemuArch, error) {
	machineType := config.HypervisorMachineType
	if machineType == "" {
		machineType = defaultQemuMachineType
	}

	if machineType != defaultQemuMachineType {
		return nil, fmt.Errorf("unrecognised machinetype: %v", machineType)
	}

	q := &qemuArm64{
		qemuArchBase{
			qemuMachine:          supportedQemuMachine,
			qemuExePath:          defaultQemuPath,
			memoryOffset:         config.MemOffset,
			kernelParamsNonDebug: kernelParamsNonDebug,
			kernelParamsDebug:    kernelParamsDebug,
			kernelParams:         kernelParams,
			disableNvdimm:        config.DisableImageNvdimm,
			dax:                  true,
			protection:           noneProtection,
			legacySerial:         config.LegacySerial,
		},
	}

	if config.ConfidentialGuest {
		if err := q.enableProtection(); err != nil {
			return nil, err
		}

		if !q.qemuArchBase.disableNvdimm {
			hvLogger.WithField("subsystem", "qemuArm64").Warn("Nvdimm is not supported with confidential guest, disabling it.")
			q.qemuArchBase.disableNvdimm = true
		}
	}

	if err := q.handleImagePath(config); err != nil {
		return nil, err
	}

	return q, nil
}

func (q *qemuArm64) bridges(number uint32) {
	q.Bridges = genericBridges(number, q.qemuMachine.Type)
}

func (q *qemuArm64) appendImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {

	if !q.disableNvdimm {
		return q.appendNvdimmImage(devices, path)
	}
	return q.appendBlockImage(devices, path)
}

// There is no nvdimm/readonly feature in qemu 5.1 which is used by arm64 for now,
// so we temporarily add this specific implementation for arm64 here until
// the qemu used by arm64 is capable for that feature
func (q *qemuArm64) appendNvdimmImage(devices []govmmQemu.Device, path string) ([]govmmQemu.Device, error) {
	object := govmmQemu.Object{
		Driver:   govmmQemu.NVDIMM,
		Type:     govmmQemu.MemoryBackendFile,
		DeviceID: "nv0",
		ID:       "mem0",
		MemPath:  path,
	}

	devices = append(devices, object)

	return devices, nil
}

func (q *qemuArm64) setIgnoreSharedMemoryMigrationCaps(_ context.Context, _ *govmmQemu.QMP) error {
	// x-ignore-shared not support in arm64 for now
	return nil
}

func (q *qemuArm64) appendIOMMU(devices []govmmQemu.Device) ([]govmmQemu.Device, error) {
	return devices, fmt.Errorf("Arm64 architecture does not support vIOMMU")
}

func (q *qemuArm64) append9PVolume(_ context.Context, devices []govmmQemu.Device, volume types.Volume) ([]govmmQemu.Device, error) {
	d, err := genericAppend9PVolume(devices, volume, q.nestedRun)
	if err != nil {
		return nil, err
	}

	d.Multidev = ""
	devices = append(devices, d)
	return devices, nil
}

func (q *qemuArm64) getPFlash() ([]string, error) {
	length := len(q.PFlash)
	if length == 0 {
		return nil, nil
	} else if length == 1 {
		return nil, fmt.Errorf("two pflash images needed for arm64")
	} else if length == 2 {
		return q.PFlash, nil
	} else {
		return nil, fmt.Errorf("too many pflash images for arm64")
	}
}

func (q *qemuArm64) enableProtection() error {
	var err error
	q.protection, err = availableGuestProtection()
	if err != nil {
		return err
	}

	logger := hvLogger.WithFields(logrus.Fields{
		"subsystem":               "qemuArm64",
		"machine":                 q.qemuMachine,
		"kernel-params-debug":     q.kernelParamsDebug,
		"kernel-params-non-debug": q.kernelParamsNonDebug,
		"kernel-params":           q.kernelParams})

	switch q.protection {
	case virtccaProtection:
		if q.qemuMachine.Options != "" {
			q.qemuMachine.Options += ","
		}
		q.qemuMachine.Options += "kernel_irqchip=on,kvm-type=cvm"
		logger.Info("Enabling Arm VirtCCA Protection")
		return nil
	default:
		return fmt.Errorf("This system doesn't support Confidential Computing (Guest Protection)")
	}
}

func (q *qemuArm64) appendProtectionDevice(devices []govmmQemu.Device, firmware, firmwareVolume string) ([]govmmQemu.Device, string, error) {
	switch q.protection {
	case virtccaProtection:
		return append(devices,
			govmmQemu.Object{
				Type:  govmmQemu.VirtCCAGuest,
				ID:    "tmm0",
				Debug: false,
				File:  firmware,
			}), "",nil

	case noneProtection:
		return devices, firmware, nil
	default:
		return devices, "", fmt.Errorf("Unsupported guest protection technology: %v", q.protection)
	}
}

// RootfsDriver describes a rootfs driver.
type RootfsDriver string

const (
	// VirtioBlk is the Virtio-Blk rootfs driver.
	VirtioBlk RootfsDriver = "/dev/vda1"

	// Nvdimm is the Nvdimm rootfs driver.
	Nvdimm RootfsType = "/dev/pmem0p1"
)

// ********** kata-containers\src\runtime\virtcontainers\hypervisor.go **********
var (
	hvLogger                   = logrus.WithField("source", "virtcontainers/hypervisor")
	noGuestMemHotplugErr error = errors.New("guest memory hotplug not supported")
	conflictingAssets    error = errors.New("cannot set both image and initrd at the same time")
)

// RootfsType describes a rootfs type.
type RootfsType string

const (
	// EXT4 is the ext4 filesystem.
	EXT4 RootfsType = "ext4"

	// XFS is the xfs filesystem.
	XFS RootfsType = "xfs"

	// EROFS is the erofs filesystem.
	EROFS RootfsType = "erofs"
)

func GetKernelRootParams(rootfstype string, disableNvdimm bool, dax bool) ([]Param, error) {
	var kernelRootParams []Param

	// EXT4 filesystem is used by default.
	if rootfstype == "" {
		rootfstype = string(EXT4)
	}

	if disableNvdimm && dax {
		return []Param{}, fmt.Errorf("Virtio-Blk does not support DAX")
	}

	if disableNvdimm {
		// Virtio-Blk
		kernelRootParams = append(kernelRootParams, Param{"root", string(VirtioBlk)})
	} else {
		// Nvdimm
		kernelRootParams = append(kernelRootParams, Param{"root", string(Nvdimm)})
	}

	switch RootfsType(rootfstype) {
	case EROFS:
		if dax {
			kernelRootParams = append(kernelRootParams, Param{"rootflags", "dax ro"})
		} else {
			kernelRootParams = append(kernelRootParams, Param{"rootflags", "ro"})
		}
	case XFS:
		fallthrough
	// EXT4 filesystem is used by default.
	case EXT4:
		if dax {
			kernelRootParams = append(kernelRootParams, Param{"rootflags", "dax,data=ordered,errors=remount-ro ro"})
		} else {
			kernelRootParams = append(kernelRootParams, Param{"rootflags", "data=ordered,errors=remount-ro ro"})
		}
	default:
		return []Param{}, fmt.Errorf("unsupported rootfs type")
	}

	kernelRootParams = append(kernelRootParams, Param{"rootfstype", rootfstype})

	return kernelRootParams, nil
}

// AddKernelParam allows the addition of new kernel parameters to an existing
// hypervisor configuration.
func (conf *HypervisorConfig) AddKernelParam(p Param) error {
	if p.Key == "" {
		return fmt.Errorf("Empty kernel parameter")
	}

	conf.KernelParams = append(conf.KernelParams, p)

	return nil
}

func (conf *HypervisorConfig) AddCustomAsset(a *types.Asset) error {
	if a == nil || a.Path() == "" {
		// We did not get a custom asset, we will use the default one.
		return nil
	}

	if !a.Valid() {
		return fmt.Errorf("Invalid %s at %s", a.Type(), a.Path())
	}

	hvLogger.Debugf("Using custom %v asset %s", a.Type(), a.Path())

	if conf.customAssets == nil {
		conf.customAssets = make(map[types.AssetType]*types.Asset)
	}

	conf.customAssets[a.Type()] = a

	return nil
}

// ImageOrInitrdAssetPath returns an image or an initrd path, along with the corresponding asset type
// Annotation path is preferred to config path.
func (conf *HypervisorConfig) ImageOrInitrdAssetPath() (string, types.AssetType, error) {
	var image, initrd string

	checkAndReturn := func(image string, initrd string) (string, types.AssetType, error) {
		if image != "" && initrd != "" {
			return "", types.UnkownAsset, conflictingAssets
		}

		if image != "" {
			return image, types.ImageAsset, nil
		}

		if initrd != "" {
			return initrd, types.InitrdAsset, nil
		}

		// Even if neither image nor initrd are set, we still need to return
		// if we are running a confidential guest on QemuCCWVirtio. (IBM Z Secure Execution)
		if conf.ConfidentialGuest && conf.HypervisorMachineType == QemuCCWVirtio {
			return "", types.SecureBootAsset, nil
		}

		return "", types.UnkownAsset, fmt.Errorf("one of image and initrd must be set")
	}

	if a, ok := conf.customAssets[types.ImageAsset]; ok {
		image = a.Path()
	}

	if a, ok := conf.customAssets[types.InitrdAsset]; ok {
		initrd = a.Path()
	}

	path, assetType, err := checkAndReturn(image, initrd)
	if assetType != types.UnkownAsset {
		return path, assetType, nil
	}
	if err == conflictingAssets {
		return "", types.UnkownAsset, errors.Wrapf(err, "conflicting annotations")
	}

	return checkAndReturn(conf.ImagePath, conf.InitrdPath)
}

func (conf *HypervisorConfig) assetPath(t types.AssetType) (string, error) {
	// Custom assets take precedence over the configured ones
	a, ok := conf.customAssets[t]
	if ok {
		return a.Path(), nil
	}

	// We could not find a custom asset for the given type, let's
	// fall back to the configured ones.
	switch t {
	case types.KernelAsset:
		return conf.KernelPath, nil
	case types.ImageAsset:
		return conf.ImagePath, nil
	case types.InitrdAsset:
		return conf.InitrdPath, nil
	case types.HypervisorAsset:
		return conf.HypervisorPath, nil
	case "hypervisorctl":
		return conf.HypervisorCtlPath, nil
	case types.JailerAsset:
		return conf.JailerPath, nil
	case types.FirmwareAsset:
		return conf.FirmwarePath, nil
	case types.FirmwareVolumeAsset:
		return conf.FirmwareVolumePath, nil
	default:
		return "", fmt.Errorf("Unknown asset type %v", t)
	}
}

// KernelAssetPath returns the guest kernel path
func (conf *HypervisorConfig) KernelAssetPath() (string, error) {
	return conf.assetPath(types.KernelAsset)
}

// ImageAssetPath returns the guest image path
func (conf *HypervisorConfig) ImageAssetPath() (string, error) {
	return conf.assetPath(types.ImageAsset)
}

// InitrdAssetPath returns the guest initrd path
func (conf *HypervisorConfig) InitrdAssetPath() (string, error) {
	return conf.assetPath(types.InitrdAsset)
}

// HypervisorAssetPath returns the VM hypervisor path
func (conf *HypervisorConfig) HypervisorAssetPath() (string, error) {
	return conf.assetPath(types.HypervisorAsset)
}

func (conf *HypervisorConfig) IfPVPanicEnabled() bool {
	return conf.GuestMemoryDumpPath != ""
}

// FirmwareAssetPath returns the guest firmware path
func (conf *HypervisorConfig) FirmwareAssetPath() (string, error) {
	return conf.assetPath(types.FirmwareAsset)
}

// FirmwareVolumeAssetPath returns the guest firmware volume path
func (conf *HypervisorConfig) FirmwareVolumeAssetPath() (string, error) {
	return conf.assetPath(types.FirmwareVolumeAsset)
}

func RoundUpNumVCPUs(cpus float32) uint32 {
	return uint32(math.Ceil(float64(cpus)))
}

func (conf HypervisorConfig) NumVCPUs() uint32 {
	return RoundUpNumVCPUs(conf.NumVCPUsF)
}

// const GOARCH string = goarch.GOARCH
func CPUFlags(cpuInfoPath string) (map[string]bool, error) {
	flagsField := "flags"

	f, err := os.Open(cpuInfoPath)
	if err != nil {
		return map[string]bool{}, err
	}
	defer f.Close()

	flags := make(map[string]bool)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		// Expected format: ["flags", ":", ...] or ["flags:", ...]
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}

		if !strings.HasPrefix(fields[0], flagsField) {
			continue
		}

		for _, field := range fields[1:] {
			flags[field] = true
		}

		return flags, nil
	}

	if err := scanner.Err(); err != nil {
		return map[string]bool{}, err
	}

	return map[string]bool{}, fmt.Errorf("Couldn't find %q from %q output", flagsField, cpuInfoPath)
}

// RunningOnVMM checks if the system is running inside a VM.
func RunningOnVMM(cpuInfoPath string) (bool, error) {
	if goruntime.GOARCH == "amd64" {
		flags, err := CPUFlags(cpuInfoPath)
		if err != nil {
			return false, err
		}
		return flags["hypervisor"], nil
	}

	hvLogger.WithField("arch", goruntime.GOARCH).Info("Unable to know if the system is running inside a VM")
	return false, nil
}

// ********** kata-containers\src\runtime\virtcontainers\qemu.go **********
type qmpChannel struct {
	qmp     *govmmQemu.QMP
	ctx     context.Context
	disconn chan struct{}
	path    string
	sync.Mutex
}

// QemuState keeps Qemu's state
type QemuState struct {
	UUID              string
	HotPlugVFIO       gt_config.PCIePort
	Bridges           []types.Bridge
	HotpluggedVCPUs   []hv.CPUDevice
	HotpluggedMemory  int
	VirtiofsDaemonPid int
	HotplugVFIO       gt_config.PCIePort
	ColdPlugVFIO      gt_config.PCIePort
	PCIeRootPort      uint32
	PCIeSwitchPort    uint32
}

// qemu is an Hypervisor interface implementation for the Linux qemu hypervisor.
// nolint: govet
type qemu struct {
	arch qemuArch

	virtiofsDaemon vc.VirtiofsDaemon

	ctx context.Context

	// fds is a list of file descriptors inherited by QEMU process
	// they'll be closed once QEMU process is running
	fds []*os.File

	id string

	state QemuState

	qmpMonitorCh qmpChannel

	qemuConfig govmmQemu.Config

	config HypervisorConfig

	// if in memory dump progress
	memoryDumpFlag sync.Mutex

	nvdimmCount int

	stopped int32

	mu sync.Mutex
}

const (
	consoleSocket      = "console.sock"
	qmpSocket          = "qmp.sock"
	extraMonitorSocket = "extra-monitor.sock"
	vhostFSSocket      = "vhost-fs.sock"
	nydusdAPISock      = "nydusd-api.sock"

	// memory dump format will be set to elf
	memoryDumpFormat = "elf"

	qmpCapErrMsg  = "Failed to negotiate QMP Capabilities"
	qmpExecCatCmd = "exec:cat"

	scsiControllerID         = "scsi0"
	rngID                    = "rng0"
	fallbackFileBackedMemDir = "/dev/shm"

	qemuStopSandboxTimeoutSecs = 15

	qomPathPrefix = "/machine/peripheral/"
)

// agnostic list of kernel parameters
var defaultKernelParameters = []Param{
	{"panic", "1"},
}

type qmpLogger struct {
	logger *logrus.Entry
}

func newQMPLogger() qmpLogger {
	return qmpLogger{
		logger: hvLogger.WithField("subsystem", "qmp"),
	}
}

func (l qmpLogger) V(level int32) bool {
	return level != 0
}

func (l qmpLogger) Infof(format string, v ...interface{}) {
	l.logger.Infof(format, v...)
}

func (l qmpLogger) Warningf(format string, v ...interface{}) {
	l.logger.Warnf(format, v...)
}

func (l qmpLogger) Errorf(format string, v ...interface{}) {
	l.logger.Errorf(format, v...)
}

// Logger returns a logrus logger appropriate for logging qemu messages
func (q *qemu) Logger() *logrus.Entry {
	return hvLogger.WithField("subsystem", "qemu")
}

func (q *qemu) kernelParameters() string {
	// get a list of arch kernel parameters
	params := q.arch.kernelParameters(q.config.Debug)

	// use default parameters
	params = append(params, defaultKernelParameters...)

	// set the maximum number of vCPUs
	params = append(params, Param{"nr_cpus", fmt.Sprintf("%d", q.config.DefaultMaxVCPUs)})

	// set the SELinux params in accordance with the runtime configuration, disable_guest_selinux.
	if q.config.DisableGuestSeLinux {
		q.Logger().Info("Set selinux=0 to kernel params because SELinux on the guest is disabled")
		params = append(params, Param{"selinux", "0"})
	} else {
		q.Logger().Info("Set selinux=1 to kernel params because SELinux on the guest is enabled")
		params = append(params, Param{"selinux", "1"})
	}

	// add the params specified by the provided config. As the kernel
	// honours the last parameter value set and since the config-provided
	// params are added here, they will take priority over the defaults.
	params = append(params, q.config.KernelParams...)

	paramsStr := SerializeParams(params, "=")

	return strings.Join(paramsStr, " ")
}

// Adds all capabilities supported by qemu implementation of hypervisor interface
func (q *qemu) Capabilities(ctx context.Context) types.Capabilities {
	// span, _ := katatrace.Trace(ctx, q.Logger(), "Capabilities", qemuTracingTags, map[string]string{"sandbox_id": q.id})
	// defer span.End()

	return q.arch.capabilities(q.config)
}

func (q *qemu) HypervisorConfig() HypervisorConfig {
	return q.config
}

// get the QEMU binary path
func (q *qemu) qemuPath() (string, error) {
	p, err := q.config.HypervisorAssetPath()
	if err != nil {
		return "", err
	}

	if p == "" {
		p = q.arch.qemuPath()
	}

	if _, err = os.Stat(p); os.IsNotExist(err) {
		return "", fmt.Errorf("QEMU path (%s) does not exist", p)
	}

	return p, nil
}

func (q *qemu) setup(id string, hypervisorConfig *HypervisorConfig) error {

	if err := q.setConfig(hypervisorConfig); err != nil {
		return err
	}

	q.id = id

	var err error

	q.arch, err = newQemuArch(q.config)
	if err != nil {
		return err
	}

	initrdPath, err := q.config.InitrdAssetPath()
	if err != nil {
		return err
	}
	imagePath, err := q.config.ImageAssetPath()
	if err != nil {
		return err
	}
	if initrdPath == "" && imagePath != "" && !q.config.DisableImageNvdimm {
		q.nvdimmCount = 1
	} else {
		q.nvdimmCount = 0
	}

	var create bool
	if q.state.UUID == "" {
		create = true
	}

	q.arch.setBridges(q.state.Bridges)
	q.arch.setPFlash(q.config.PFlash)

	if create {
		// q.Logger().Debug("Creating bridges")
		q.arch.bridges(q.config.DefaultBridges)

		// q.Logger().Debug("Creating UUID")
		q.state.UUID = uuid.Generate().String()
		q.state.HotPlugVFIO = q.config.HotPlugVFIO
		q.state.ColdPlugVFIO = q.config.ColdPlugVFIO
		q.state.PCIeRootPort = q.config.PCIeRootPort
		q.state.PCIeSwitchPort = q.config.PCIeSwitchPort

		// The path might already exist, but in case of VM templating,
		// we have to create it since the sandbox has not created it yet.
		// if err = utils.MkdirAllWithInheritedOwner(filepath.Join(q.config.RunStorePath, id), DirMode); err != nil {
		// 	return err
		// }
	}

	nested, err := RunningOnVMM(procCPUInfo)
	if err != nil {
		return err
	}

	if !q.config.DisableNestingChecks && nested {
		q.arch.enableNestingChecks()
	} else {
		// q.Logger().WithField("inside-vm", fmt.Sprintf("%t", nested)).Debug("Disable nesting environment checks")
		q.arch.disableNestingChecks()
	}

	if !q.config.DisableVhostNet {
		q.arch.enableVhostNet()
	} else {
		// q.Logger().Debug("Disable vhost_net")
		q.arch.disableVhostNet()
	}

	return nil
}

func (q *qemu) cpuTopology() govmmQemu.SMP {
	return q.arch.cpuTopology(q.config.NumVCPUs(), q.config.DefaultMaxVCPUs)
}

func (q *qemu) memoryTopology() (govmmQemu.Memory, error) {
	hostMemMb := q.config.DefaultMaxMemorySize
	memMb := uint64(q.config.MemorySize)

	return q.arch.memoryTopology(memMb, hostMemMb, uint8(q.config.MemSlots)), nil
}

func (q *qemu) qmpSocketPath(id string) (string, error) {
	return utils.BuildSocketPath(q.config.VMStorePath, id, qmpSocket)
}

func (q *qemu) extraMonitorSocketPath(id string) (string, error) {
	return utils.BuildSocketPath(q.config.VMStorePath, id, extraMonitorSocket)
}

func (q *qemu) getQemuMachine() (govmmQemu.Machine, error) {
	machine := q.arch.machine()

	accelerators := q.config.MachineAccelerators
	if accelerators != "" {
		if !strings.HasPrefix(accelerators, ",") {
			accelerators = fmt.Sprintf(",%s", accelerators)
		}
		machine.Options += accelerators
	}

	return machine, nil
}

func (q *qemu) createQmpSocket() ([]govmmQemu.QMPSocket, error) {
	monitorSockPath, err := q.qmpSocketPath(q.id)
	if err != nil {
		return nil, err
	}

	q.qmpMonitorCh = qmpChannel{
		ctx:  q.ctx,
		path: monitorSockPath,
	}

	var sockets []govmmQemu.QMPSocket

	sockets = append(sockets, govmmQemu.QMPSocket{
		Type:     "unix",
		Protocol: govmmQemu.Qmp,
		Server:   true,
		NoWait:   true,
	})

	// The extra monitor socket allows an external user to take full
	// control on Qemu and silently break the VM in all possible ways.
	// It should only ever be used for debugging purposes, hence the
	// check on Debug.
	if q.HypervisorConfig().Debug && q.config.ExtraMonitorSocket != "" {
		extraMonitorSockPath, err := q.extraMonitorSocketPath(q.id)
		if err != nil {
			return nil, err
		}

		sockets = append(sockets, govmmQemu.QMPSocket{
			Type:     "unix",
			Protocol: q.config.ExtraMonitorSocket,
			Name:     extraMonitorSockPath,
			Server:   true,
			NoWait:   true,
		})

		q.Logger().Warn("QEMU configured to start with an untrusted monitor")
	}

	return sockets, nil
}

func (q *qemu) buildDevices(kernelPath string) ([]govmmQemu.Device, *govmmQemu.IOThread, *govmmQemu.Kernel, error) {
	var devices []govmmQemu.Device

	kernel := &govmmQemu.Kernel{
		Path: kernelPath,
	}

	_, console, err := q.GetVMConsole(q.id)
	if err != nil {
		return nil, nil, nil, err
	}

	// Add bridges before any other devices. This way we make sure that
	// bridge gets the first available PCI address i.e bridgePCIStartAddr
	devices = q.arch.appendBridges(devices)

	devices, err = q.arch.appendConsole(devices, console)
	if err != nil {
		return nil, nil, nil, err
	}

	assetPath, assetType, err := q.config.ImageOrInitrdAssetPath()
	if err != nil {
		return nil, nil, nil, err
	}

	if assetType == types.ImageAsset {
		devices, err = q.arch.appendImage(devices, assetPath)
		if err != nil {
			return nil, nil, nil, err
		}
	} else if assetType == types.InitrdAsset {
		// InitrdAsset, need to set kernel initrd path
		kernel.InitrdPath = assetPath
	} else if assetType == types.SecureBootAsset {
		// SecureBootAsset, no need to set image or initrd path
		q.Logger().Info("For IBM Z Secure Execution, initrd path should not be set")
		kernel.InitrdPath = ""
	}

	if q.config.IOMMU {
		devices, err = q.arch.appendIOMMU(devices)
		if err != nil {
			return nil, nil, nil, err
		}
	}

	if q.config.IfPVPanicEnabled() {
		// there should have no errors for pvpanic device
		devices, _ = q.arch.appendPVPanicDevice(devices)
	}

	var ioThread *govmmQemu.IOThread
	if q.config.BlockDeviceDriver == gt_config.VirtioSCSI {
		devices, ioThread, err = q.arch.appendSCSIController(devices, q.config.EnableIOThreads)
		if err != nil {
			return nil, nil, nil, err
		}
	}

	return devices, ioThread, kernel, nil
}

func (q *qemu) setupTemplate(knobs *govmmQemu.Knobs, memory *govmmQemu.Memory) govmmQemu.Incoming {
	incoming := govmmQemu.Incoming{}

	if q.config.BootToBeTemplate || q.config.BootFromTemplate {
		knobs.FileBackedMem = true
		memory.Path = q.config.MemoryPath

		if q.config.BootToBeTemplate {
			knobs.MemShared = true
		}

		if q.config.BootFromTemplate {
			incoming.MigrationType = govmmQemu.MigrationDefer
		}
	}

	return incoming
}

func (q *qemu) setupFileBackedMem(knobs *govmmQemu.Knobs, memory *govmmQemu.Memory) {
	var target string
	if q.config.FileBackedMemRootDir != "" {
		target = q.config.FileBackedMemRootDir
	} else {
		target = fallbackFileBackedMemDir
	}
	if _, err := os.Stat(target); err != nil {
		q.Logger().WithError(err).Error("File backed memory location does not exist")
		return
	}

	knobs.FileBackedMem = true
	knobs.MemShared = true
	memory.Path = target
}

func (q *qemu) setConfig(config *HypervisorConfig) error {
	q.config = *config

	return nil
}

// ********** kata-containers\src\runtime\virtcontainers\nydusd_linux.go **********
const shimNsPath = "/proc/self/ns/net"

func startInShimNS(cmd *exec.Cmd) error {
	// Create nydusd in shim netns as it needs to access host network
	return doNetNS(shimNsPath, func(_ ns.NetNS) error {
		return cmd.Start()
	})
}

// ********** kata-containers\src\runtime\virtcontainers\network_linux.go **********
// doNetNS is free from any call to a go routine, and it calls
// into runtime.LockOSThread(), meaning it won't be executed in a
// different thread than the one expected by the caller.
func doNetNS(netNSPath string, cb func(ns.NetNS) error) error {
	// if netNSPath is empty, the callback function will be run in the current network namespace.
	// So skip the whole function, just call cb(). cb() needs a NetNS as arg but ignored, give it a fake one.
	if netNSPath == "" {
		var netNs ns.NetNS
		return cb(netNs)
	}

	goruntime.LockOSThread()
	defer goruntime.UnlockOSThread()

	currentNS, err := ns.GetCurrentNS()
	if err != nil {
		return err
	}
	defer currentNS.Close()

	targetNS, err := ns.GetNS(netNSPath)
	if err != nil {
		return err
	}

	if err := targetNS.Set(); err != nil {
		return err
	}
	defer currentNS.Set()

	return cb(targetNS)
}

// ********** kata-containers\src\runtime\virtcontainers\qemu.go **********
// CreateVM is the Hypervisor VM creation implementation for govmmQemu.
func (q *qemu) CreateVM(id string, hypervisorConfig *HypervisorConfig) error {
	if err := q.setup(id, hypervisorConfig); err != nil {
		return err
	}

	machine, err := q.getQemuMachine()
	if err != nil {
		return err
	}

	smp := q.cpuTopology()

	memory, err := q.memoryTopology()
	if err != nil {
		return err
	}

	knobs := govmmQemu.Knobs{
		NoUserConfig:  true,
		NoDefaults:    true,
		NoGraphic:     true,
		NoReboot:      true,
		MemPrealloc:   q.config.MemPrealloc,
		HugePages:     q.config.HugePages,
		IOMMUPlatform: q.config.IOMMUPlatform,
	}

	incoming := q.setupTemplate(&knobs, &memory)

	// With the current implementations, VM templating will not work with file
	// based memory (stand-alone) or virtiofs. This is because VM templating
	// builds the first VM with file-backed memory and shared=on and the
	// subsequent ones with shared=off. virtio-fs always requires shared=on for
	// memory.
	if q.config.SharedFS == gt_config.VirtioFS || q.config.SharedFS == gt_config.VirtioFSNydus ||
		q.config.FileBackedMemRootDir != "" {
		if !(q.config.BootToBeTemplate || q.config.BootFromTemplate) {
			q.setupFileBackedMem(&knobs, &memory)
		} else {
			return errors.New("VM templating has been enabled with either virtio-fs or file backed memory and this configuration will not work")
		}
		if q.config.HugePages {
			knobs.MemPrealloc = true
		}
	}

	// Vhost-user-blk/scsi process which can improve performance, like SPDK,
	// requires shared-on hugepage to work with Qemu.
	if q.config.EnableVhostUserStore {
		if !q.config.HugePages {
			return errors.New("Vhost-user-blk/scsi is enabled without HugePages. This configuration will not work")
		}
		knobs.MemShared = true
	}

	rtc := govmmQemu.RTC{
		Base:     govmmQemu.UTC,
		Clock:    govmmQemu.Host,
		DriftFix: govmmQemu.Slew,
	}

	if q.state.UUID == "" {
		return fmt.Errorf("UUID should not be empty")
	}

	qmpSockets, err := q.createQmpSocket()
	if err != nil {
		return err
	}

	kernelPath, err := q.config.KernelAssetPath()
	if err != nil {
		return err
	}

	devices, ioThread, kernel, err := q.buildDevices(kernelPath)
	if err != nil {
		return err
	}

	cpuModel := q.arch.cpuModel()
	cpuModel += "," + q.config.CPUFeatures

	firmwarePath, err := q.config.FirmwareAssetPath()
	if err != nil {
		return err
	}

	firmwareVolumePath, err := q.config.FirmwareVolumeAssetPath()
	if err != nil {
		return err
	}

	pflash, err := q.arch.getPFlash()
	if err != nil {
		return err
	}

	qemuPath, err := q.qemuPath()
	if err != nil {
		return err
	}

	// some devices configuration may also change kernel params, make sure this is called afterwards
	kernel.Params = q.kernelParameters()
	q.checkBpfEnabled()

	qemuConfig := govmmQemu.Config{
		Name:           fmt.Sprintf("sandbox-%s", q.id),
		UUID:           q.state.UUID,
		Path:           qemuPath,
		Uid:            q.config.Uid,
		Gid:            q.config.Gid,
		Groups:         q.config.Groups,
		Machine:        machine,
		SMP:            smp,
		Memory:         memory,
		Devices:        devices,
		CPUModel:       cpuModel,
		SeccompSandbox: q.config.SeccompSandbox,
		Kernel:         *kernel,
		RTC:            rtc,
		QMPSockets:     qmpSockets,
		Knobs:          knobs,
		Incoming:       incoming,
		VGA:            "none",
		GlobalParam:    "kvm-pit.lost_tick_policy=discard",
		Bios:           firmwarePath,
		PFlash:         pflash,
		PidFile:        filepath.Join(q.config.VMStorePath, q.id, "pid"),
		Debug:          hypervisorConfig.Debug,
	}

	qemuConfig.Devices, qemuConfig.Bios, err = q.arch.appendProtectionDevice(qemuConfig.Devices, firmwarePath, firmwareVolumePath)
	if err != nil {
		return err
	}

	if ioThread != nil {
		qemuConfig.IOThreads = []govmmQemu.IOThread{*ioThread}
	}
	// Add RNG device to hypervisor
	// Skip for s390x as CPACF is used
	if machine.Type != QemuCCWVirtio {
		rngDev := gt_config.RNGDev{
			ID:       rngID,
			Filename: q.config.EntropySource,
		}
		qemuConfig.Devices, err = q.arch.appendRNGDevice(qemuConfig.Devices, rngDev)
		if err != nil {
			return err
		}
	}

	if machine.Type == QemuQ35 || machine.Type == QemuVirt {
		if err := q.createPCIeTopology(&qemuConfig, hypervisorConfig, machine.Type); err != nil {
			q.Logger().WithError(err).Errorf("Cannot create PCIe topology")
			return err
		}
	}
	q.qemuConfig = qemuConfig

	// q.virtiofsDaemon, err = q.createVirtiofsDaemon(hypervisorConfig.SharedPath)
	return err
}

func (q *qemu) checkBpfEnabled() {
	if q.config.SeccompSandbox != "" {
		out, err := os.ReadFile("/proc/sys/net/core/bpf_jit_enable")
		if err != nil {
			q.Logger().WithError(err).Warningf("failed to get bpf_jit_enable status")
			return
		}
		enabled, err := strconv.Atoi(strings.TrimSpace(string(out)))
		if err != nil {
			q.Logger().WithError(err).Warningf("failed to convert bpf_jit_enable status to integer")
			return
		}
		if enabled == 0 {
			q.Logger().Warningf("bpf_jit_enable is disabled. " +
				"It's recommended to turn on bpf_jit_enable to reduce the performance impact of QEMU seccomp sandbox.")
		}
	}
}

// If a user uses 8 GPUs with 4 devices in each IOMMU Group that means we need
// to hotplug 32 devices. We do not have enough PCIe root bus slots to
// accomplish this task. Kata will use already some slots for vfio-xxxx-pci
// devices.
// Max PCI slots per root bus is 32
// Max PCIe root ports is 16
// Max PCIe switch ports is 16
// There is only 64kB of IO memory each root,switch port will consume 4k hence
// only 16 ports possible.
func (q *qemu) createPCIeTopology(qemuConfig *govmmQemu.Config, hypervisorConfig *HypervisorConfig, machineType string) error {

	// If no-port set just return no need to add PCIe Root Port or PCIe Switches
	if hypervisorConfig.HotPlugVFIO == gt_config.NoPort && hypervisorConfig.ColdPlugVFIO == gt_config.NoPort && machineType == QemuQ35 {
		return nil
	}

	// Add PCIe Root Port or PCIe Switches to the hypervisor
	// The pcie.0 bus do not support hot-plug, but PCIe device can be hot-plugged
	// into a PCIe Root Port or PCIe Switch.
	// For more details, please see https://github.com/qemu/qemu/blob/master/docs/pcie.txt

	// Deduce the right values for mem-reserve and pref-64-reserve memory regions
	memSize32bit, memSize64bit := q.arch.getBARsMaxAddressableMemory()

	// The default OVMF MMIO aperture is too small for some PCIe devices
	// with huge BARs so we need to increase it.
	// memSize64bit is in bytes, convert to MB, OVMF expects MB as a string
	if strings.Contains(strings.ToLower(hypervisorConfig.FirmwarePath), "ovmf") {
		pciMmio64Mb := fmt.Sprintf("%d", (memSize64bit / 1024 / 1024))
		fwCfg := govmmQemu.FwCfg{
			Name: "opt/ovmf/X-PciMmio64Mb",
			Str:  pciMmio64Mb,
		}
		qemuConfig.FwCfg = append(qemuConfig.FwCfg, fwCfg)
	}

	// Get the number of hot(cold)-pluggable ports needed from the provided
	// VFIO devices
	var numOfPluggablePorts uint32 = 0

	// Fow now, pcie native hotplug is the only way for Arm to hotadd pci device.
	if machineType == QemuVirt {
		epNum, err := GetEndpointsNum()
		if err != nil {
			q.Logger().Warn("Fail to get network endpoints number")
		}
		virtPcieRootPortNum := len(hypervisorConfig.VhostUserBlkDevices) + epNum
		if hypervisorConfig.VirtioMem {
			virtPcieRootPortNum++
		}
		numOfPluggablePorts += uint32(virtPcieRootPortNum)
	}
	for _, dev := range hypervisorConfig.VFIODevices {
		var err error
		dev.HostPath, err = gt_config.GetHostPath(dev, false, "")
		if err != nil {
			return fmt.Errorf("Cannot get host path for device: %v err: %v", dev, err)
		}

		var vfioDevices []*gt_config.VFIODev
		// This works for IOMMUFD enabled kernels > 6.x
		// In the case of IOMMUFD the device.HostPath will look like
		// /dev/vfio/devices/vfio0
		// (1) Check if we have the new IOMMUFD or old container based VFIO
		if strings.HasPrefix(dev.HostPath, drivers.IommufdDevPath) {
			q.Logger().Infof("### IOMMUFD Path: %s", dev.HostPath)
			vfioDevices, err = drivers.GetDeviceFromVFIODev(dev)
			if err != nil {
				return fmt.Errorf("Cannot get VFIO device from IOMMUFD with device: %v err: %v", dev, err)
			}
		} else {
			vfioDevices, err = drivers.GetAllVFIODevicesFromIOMMUGroup(dev)
			if err != nil {
				return fmt.Errorf("Cannot get all VFIO devices from IOMMU group with device: %v err: %v", dev, err)
			}
		}

		for _, vfioDevice := range vfioDevices {
			if drivers.IsPCIeDevice(vfioDevice.BDF) {
				numOfPluggablePorts = numOfPluggablePorts + 1
			}
		}
	}
	vfioOnRootPort := (q.state.HotPlugVFIO == gt_config.RootPort || q.state.ColdPlugVFIO == gt_config.RootPort)
	vfioOnSwitchPort := (q.state.HotPlugVFIO == gt_config.SwitchPort || q.state.ColdPlugVFIO == gt_config.SwitchPort)

	// If the devices are not advertised via CRI or cold-plugged we need to
	// get the number of pluggable root/switch ports from the config
	numPCIeRootPorts := hypervisorConfig.PCIeRootPort
	numPCIeSwitchPorts := hypervisorConfig.PCIeSwitchPort

	// If number of PCIe root ports > 16 then bail out otherwise we may
	// use up all slots or IO memory on the root bus and vfio-XXX-pci devices
	// cannot be added which are crucial for Kata max slots on root bus is 32
	// max slots on the complete pci(e) topology is 256 in QEMU
	if vfioOnRootPort {
		if numOfPluggablePorts < numPCIeRootPorts {
			numOfPluggablePorts = numPCIeRootPorts
		}
		if numOfPluggablePorts > maxPCIeRootPort {
			return fmt.Errorf("Number of PCIe Root Ports exceeed allowed max of %d", maxPCIeRootPort)
		}
		qemuConfig.Devices = q.arch.appendPCIeRootPortDevice(qemuConfig.Devices, numOfPluggablePorts, memSize32bit, memSize64bit)
		return nil
	}
	if vfioOnSwitchPort {
		if numOfPluggablePorts < numPCIeSwitchPorts {
			numOfPluggablePorts = numPCIeSwitchPorts
		}
		if numOfPluggablePorts > maxPCIeSwitchPort {
			return fmt.Errorf("Number of PCIe Switch Ports exceeed allowed max of %d", maxPCIeSwitchPort)
		}
		qemuConfig.Devices = q.arch.appendPCIeSwitchPortDevice(qemuConfig.Devices, numOfPluggablePorts, memSize32bit, memSize64bit)
		return nil
	}
	// If both Root Port and Switch Port are not enabled, check if QemuVirt need add pcie root port.
	if machineType == QemuVirt {
		qemuConfig.Devices = q.arch.appendPCIeRootPortDevice(qemuConfig.Devices, numOfPluggablePorts, memSize32bit, memSize64bit)
	}
	return nil
}

func (q *qemu) vhostFSSocketPath(id string) (string, error) {
	return utils.BuildSocketPath(q.config.VMStorePath, id, vhostFSSocket)
}

func (q *qemu) nydusdAPISocketPath(id string) (string, error) {
	return utils.BuildSocketPath(q.config.VMStorePath, id, nydusdAPISock)
}

func genericAppendBridges(devices []govmmQemu.Device, bridges []types.Bridge, machineType string) []govmmQemu.Device {
	bus := defaultPCBridgeBus
	switch machineType {
	case QemuQ35, QemuVirt:
		bus = defaultBridgeBus
	}

	for idx, b := range bridges {
		t := govmmQemu.PCIBridge
		if b.Type == types.PCIE {
			t = govmmQemu.PCIEBridge
		}
		if b.Type == types.CCW {
			continue
		}

		bridges[idx].Addr = bridgePCIStartAddr + idx

		devices = append(devices,
			govmmQemu.BridgeDevice{
				Type: t,
				Bus:  bus,
				ID:   b.ID,
				// Each bridge is required to be assigned a unique chassis id > 0
				Chassis: idx + 1,
				SHPC:    false,
				Addr:    strconv.FormatInt(int64(bridges[idx].Addr), 10),
				// Certain guest BIOS versions think
				// !SHPC means no hotplug, and won't
				// reserve the IO and memory windows
				// that will be needed for devices
				// added underneath this bridge.  This
				// will only break for certain
				// combinations of exact qemu, BIOS
				// and guest kernel versions, but for
				// consistency, just hint the usual
				// default windows for a bridge (as
				// the BIOS would use with SHPC) so
				// that we can do ACPI hotplug.
				IOReserve:     "4k",
				MemReserve:    "1m",
				Pref64Reserve: "1m",
			},
		)
	}

	return devices
}

func genericBridges(number uint32, machineType string) []types.Bridge {
	var bridges []types.Bridge
	var bt types.Type

	switch machineType {
	case QemuQ35:
		// currently only pci bridges are supported
		// qemu-2.10 will introduce pcie bridges
		bt = types.PCI
	case QemuVirt:
		bt = types.PCI
	case QemuPseries:
		bt = types.PCI
	case QemuCCWVirtio:
		bt = types.CCW
	default:
		return nil
	}

	for i := uint32(0); i < number; i++ {
		bridges = append(bridges, types.NewBridge(bt, fmt.Sprintf("%s-bridge-%d", bt, i), make(map[uint32]string), 0))
	}

	return bridges
}

// nolint: unused, deadcode
func genericMemoryTopology(memoryMb, hostMemoryMb uint64, slots uint8, memoryOffset uint64) govmmQemu.Memory {
	// image NVDIMM device needs memory space 1024MB
	// See https://github.com/clearcontainers/runtime/issues/380
	memoryOffset += 1024

	memMax := fmt.Sprintf("%dM", hostMemoryMb+memoryOffset)

	mem := fmt.Sprintf("%dM", memoryMb)

	memory := govmmQemu.Memory{
		Size:   mem,
		Slots:  slots,
		MaxMem: memMax,
	}

	return memory
}

// genericAppendPCIeRootPort appends to devices the given pcie-root-port
func genericAppendPCIeRootPort(devices []govmmQemu.Device, number uint32, machineType string, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device {
	var (
		bus           string
		chassis       string
		multiFunction bool
		addr          string
	)
	switch machineType {
	case QemuQ35, QemuVirt:
		bus = defaultBridgeBus
		chassis = "0"
		multiFunction = false
		addr = "0"
	default:
		return devices
	}

	for i := uint32(0); i < number; i++ {
		devices = append(devices,
			govmmQemu.PCIeRootPortDevice{
				ID:            fmt.Sprintf("%s%d", gt_config.PCIeRootPortPrefix, i),
				Bus:           bus,
				Chassis:       chassis,
				Slot:          strconv.FormatUint(uint64(i), 10),
				Multifunction: multiFunction,
				Addr:          addr,
				MemReserve:    fmt.Sprintf("%dB", memSize32bit),
				Pref64Reserve: fmt.Sprintf("%dB", memSize64bit),
			},
		)
	}
	return devices
}

// gollangci-lint enforces multi-line comments to be a block comment
// not multiple single line comments ...
/*  pcie.0 bus
//  -------------------------------------------------
//                           |
//                     -------------
//                     | Root Port |
//                     -------------
//  -------------------------|------------------------
//  |                 -----------------              |
//  |    PCI Express  | Upstream Port |              |
//  |      Switch     -----------------              |
//  |                  |            |                |
//  |    -------------------    -------------------  |
//  |    | Downstream Port |    | Downstream Port |  |
//  |    -------------------    -------------------  |
//  -------------|-----------------------|------------
//          -------------           --------------
//          | GPU/ACCEL |           | IB/ETH NIC |
//          -------------           --------------
*/
// genericAppendPCIeSwitch adds a PCIe Swtich
func genericAppendPCIeSwitchPort(devices []govmmQemu.Device, number uint32, machineType string, memSize32bit uint64, memSize64bit uint64) []govmmQemu.Device {

	// Q35, Virt have the correct PCIe support,
	// hence ignore all other machines
	if machineType != QemuQ35 && machineType != QemuVirt {
		return devices
	}

	// Using an own ID for the root port, so we do not clash with already
	// existing root ports adding "s" for switch prefix
	pcieRootPort := govmmQemu.PCIeRootPortDevice{
		ID:            fmt.Sprintf("%s%s%d", gt_config.PCIeSwitchPortPrefix, gt_config.PCIeRootPortPrefix, 0),
		Bus:           defaultBridgeBus,
		Chassis:       "1",
		Slot:          strconv.FormatUint(uint64(0), 10),
		Multifunction: false,
		Addr:          "0",
		MemReserve:    fmt.Sprintf("%dB", memSize32bit),
		Pref64Reserve: fmt.Sprintf("%dB", memSize64bit),
	}

	devices = append(devices, pcieRootPort)

	pcieSwitchUpstreamPort := govmmQemu.PCIeSwitchUpstreamPortDevice{
		ID:  fmt.Sprintf("%s%d", gt_config.PCIeSwitchUpstreamPortPrefix, 0),
		Bus: pcieRootPort.ID,
	}
	devices = append(devices, pcieSwitchUpstreamPort)

	currentChassis, err := strconv.Atoi(pcieRootPort.Chassis)
	if err != nil {
		return devices
	}
	nextChassis := currentChassis + 1

	for i := uint32(0); i < number; i++ {

		pcieSwitchDownstreamPort := govmmQemu.PCIeSwitchDownstreamPortDevice{
			ID:      fmt.Sprintf("%s%d", gt_config.PCIeSwitchhDownstreamPortPrefix, i),
			Bus:     pcieSwitchUpstreamPort.ID,
			Chassis: fmt.Sprintf("%d", nextChassis),
			Slot:    strconv.FormatUint(uint64(i), 10),
		}
		devices = append(devices, pcieSwitchDownstreamPort)
	}

	return devices
}

// ********** kata-containers\src\runtime\virtcontainers\nydusd.go **********
type nydusd struct {
	startFn         func(cmd *exec.Cmd) error // for mock testing
	waitFn          func() error              // for mock
	setupShareDirFn func() error              // for mock testing
	path            string
	sockPath        string
	apiSockPath     string
	sourcePath      string
	extraArgs       []string
	pid             int
	debug           bool
}
