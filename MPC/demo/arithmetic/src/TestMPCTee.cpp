/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <chrono>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <future>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "data_guard_callback.h"
#include "data_guard_mpc.h"

#define BACKLOG_SIZE 16  // 请求队列最大长度

int send_sockfd = -1;
int recv_sockfd = -1;
constexpr int FXP_BITS = 8;
// arithmetic
int64_t RandGen_z0();
static int64_t GetCurrentTimestampMs();
int ExecArithmetic(DG_AlgorithmsType type, std::string inputFileName,
                   void *teeCfg, int nodeId);
int ExecSingleInputOperator(DG_AlgorithmsType type, std::string inputFileName,
                            void *teeCfg, int nodeId);
// socket
int InitServer(int port);
int InitClient(const char *ip, int port);
int senddata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len);
int send_buf(int fd, unsigned char *buf, uint64_t len);
int recvdata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len);
void close_socket();
// run mpc tee demo
int CallMpcTee(DG_AlgorithmsType type, int nodeId, std::string inputFileName);
void ExecutNet(DG_AlgorithmsType type, std::vector<std::string> data);

// log function
void WriteMpcTeeLog(int level, const char *modelName, const char *filePathName,
                    int lineNum, const char *logStr);
void PrintfDGLog(void);

int main(int argc, char **argv) {
  int i = 1;
  std::string inputfileAParty = argv[i++];
  std::string inputfileBParty = argv[i++];
  int nodeId = std::atoi(argv[i++]);

  DG_AlgorithmsType type = static_cast<DG_AlgorithmsType>(std::atoi(argv[i++]));
  std::string ip1 = argv[i++];
  std::string ip2 = argv[i++];
  std::string port1 = argv[i++];
  std::string port2 = argv[i++];
  bool isSingleInput = false;
  if (type == ASCEND_SORT || type == DESCEND_SORT || type == SUM || type == AVG) {
    isSingleInput = true;
  }
  if (isSingleInput) {
    inputfileBParty = inputfileAParty;
  }
  std::vector<std::string> data1{port1, port2, "0", inputfileAParty,
                                 "0",   ip1,   ip2};
  std::vector<std::string> data2{port2, port1, "1", inputfileBParty,
                                 "1",   ip2,   ip1};

  if (nodeId==0) {
      ExecutNet(type, data1);
  } else {
      ExecutNet(type, data2);
  }

  return 0;
}

int64_t RandGen_z0() {
  static std::random_device rd;
  static std::mt19937_64 engine(rd());

  static std::uniform_int_distribution<uint64_t> dist(INT_MIN, INT_MAX);
  return dist(engine);
}
constexpr int SINGLEOP_SHRESET_SIZE = 1;
static int64_t GetCurrentTimestampMs() {
  auto now = std::chrono::system_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::microseconds>(
      now.time_since_epoch());
  return duration.count() / 1000;
}

int ExecArithmetic(DG_AlgorithmsType type, std::string inputFileName,
                   void *teeCfg, int nodeId) {
  printf("---------DG_InitPsiOpts------------\n");
  DG_Arithmetic_Opts aritOpts = DG_InitArithmeticOpts();
  printf("---------initTeeCtx------------\n");
  struct DG_TeeCtx *dgTee = nullptr;
  int rv = aritOpts.initTeeCtx(teeCfg, &dgTee);
  if (rv != 0) {
    printf("tee init error.-%d\n", rv);
    return rv;
  }
  printf("---------setTeeNodeInfos------------\n");
  struct TeeNodeInfo teeNodes[2];
  teeNodes[0].nodeId = 0;
  teeNodes[1].nodeId = 1;
  struct TeeNodeInfos allNodes;
  allNodes.nodeInfo = teeNodes;
  allNodes.size = 2;
  rv = aritOpts.setTeeNodeInfos(dgTee, &allNodes);
  if (rv != 0) {
    printf("tee set node info error.-%d\n", rv);
    return rv;
  }

  std::ifstream ifStream(inputFileName);
  int size = 0;
  std::string line;
  std::vector<std::string> datas;
  while (std::getline(ifStream, line)) {
    datas.push_back(line);
  }

  std::unique_ptr<double[]> inData = std::make_unique<double[]>(datas.size());
  for (int i = 0; i < datas.size(); i++) {
    inData[i] = (std::stod(datas[i].c_str())) * 1.0;
  }
  DG_TeeInput teeInput;
  teeInput.data.doubleNumbers = inData.get();
  teeInput.size = static_cast<int>(datas.size());
  teeInput.dataType = MPC_DOUBLE;
  printf("++++++++++input data size:%lu\n", teeInput.size);
  int res = aritOpts.negotiateSeeds(dgTee);
  printf("exchange seed res = %d\n", res);
  std::unique_ptr<DG_MpcShare[]> share = std::make_unique<DG_MpcShare[]>(2);
  DG_MpcShare *share1 = nullptr;
  DG_MpcShare *share2 = nullptr;
  DG_TeeOutput *output = nullptr;
  if (nodeId == 0) {
    res = aritOpts.makeShare(dgTee, 1, nullptr, &share1);  // &teeInput
    if (res != 0) {
      printf("recv share data.[ret=%d]\n", res);
    }
    res = aritOpts.makeShare(dgTee, 0, &teeInput, &share2);
    if (res != 0) {
      printf("make share self shar data.[ret=%d]\n", res);
      return res;
    }
    sleep(5);
    std::unique_ptr<DG_MpcShareSet> shares = std::make_unique<DG_MpcShareSet>();
    std::unique_ptr<DG_MpcShare[]> share_datas =
        std::make_unique<DG_MpcShare[]>(2);
    share_datas[0] = *share2;
    share_datas[1] = *share1;
    shares->shareSet = share_datas.get();
    shares->size = 2;

    DG_MpcShare *share_out = nullptr;
    uint64_t start = GetCurrentTimestampMs();
    res = aritOpts.calculate(dgTee, type, shares.get(), &share_out);
    std::cout << "executeArithmeticOpts(ms):" << GetCurrentTimestampMs() - start
              << std::endl;
    if (res != 0) {
      printf("executeArithmeticOpts.[ret=%d]\n", res);
      return res;
    }
    res = aritOpts.revealShare(dgTee, share_out, &output);

    int data_size = share_datas[0].size;  // 输入的分片规模
    std::vector<int64_t> fxp_datas0(data_size);
    std::vector<int64_t> fxp_datas1(data_size);
    for (int i = 0; i < data_size; i++) {  // 计算分片对应的定点数
      fxp_datas0[i] =
          static_cast<int64_t>(share_datas[0].dataShare[i].shares[0] +
                               share_datas[0].dataShare[i].shares[1]);
      fxp_datas1[i] =
          static_cast<int64_t>(share_datas[1].dataShare[i].shares[0] +
                               share_datas[1].dataShare[i].shares[1]);
    }
    for (int i = 0; i < data_size; i++) {
      std::cout << fxp_datas0[i] << " ";
    }

    for (int i = 0; i < data_size; i++) {
      std::cout << fxp_datas1[i] << " ";
    }
    std::cout << "\n";
    std::cout << "kcal compute result shares (fxp): ";
    for (int i = 0; i < data_size; i++) {
      int64_t tmp = static_cast<int64_t>(share_out->dataShare[i].shares[0] +
                                         share_out->dataShare[i].shares[1]);
      std::cout << tmp << " ";
    }
    std::cout << "\n";
    std::cout << "kcal compute revealed result: ";
    if (output->dataType == MPC_DOUBLE) {
      for (int i = 0; i < data_size; i++) {
        std::cout << output->data.doubleNumbers[i] << " ";
      }
    } else {
      for (int i = 0; i < data_size; i++) {
        std::cout << output->data.u64Numbers[i] << " ";
      }
    }

    std::cout << "\n";
    printf("reveal res = %d\n", res);
  } else {
    res = aritOpts.makeShare(dgTee, 0, &teeInput, &share1);
    if (res != 0) {
      printf("1 make share self shar data fail.[ret=%d]\n", res);
      return res;
    }
    res = aritOpts.makeShare(dgTee, 1, &teeInput, &share2);
    if (res != 0) {
      printf("make share self shar data.[ret=%d]\n", res);
      return res;
    }
    sleep(5);
    std::unique_ptr<DG_MpcShareSet> shares = std::make_unique<DG_MpcShareSet>();
    std::unique_ptr<DG_MpcShare[]> share_datas =
        std::make_unique<DG_MpcShare[]>(2);
    share_datas[0] = *share1;
    share_datas[1] = *share2;
    shares->shareSet = share_datas.get();
    shares->size = 2;
    DG_MpcShare *share_out = nullptr;
    auto start_time = std::chrono::high_resolution_clock::now();
    res = aritOpts.calculate(dgTee, type, shares.get(), &share_out);
    if (res != 0) {
      printf("1 executeArithmeticOpts fail .[ret=%d]\n", res);
      return res;
    }
    auto end_time = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(
                        end_time - start_time)
                        .count();
    printf("node 1 executeArithmeticOpts time cost: %lu microseconds\n",
           duration);

    res = aritOpts.revealShare(dgTee, share_out, &output);
    printf("1 reveal res = %d\n", res);
  }
  aritOpts.releaseTeeCtx(&dgTee);
  aritOpts.releaseOutput(&output);
  return res;
}
int InitServer(int port) {
  int server_fd = -1;
  int client_fd = -1;
  sockaddr_in server_addr{};
  socklen_t addr_len = sizeof(server_addr);

  // 创建服务器套接字
  server_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (server_fd == -1) {
    std::cerr << "Failed to create socket: " << strerror(errno) << std::endl;
    return -1;
  }

  // 设置服务器地址
  server_addr.sin_family = AF_INET;
  server_addr.sin_addr.s_addr = INADDR_ANY;
  server_addr.sin_port = htons(port);

  // 绑定套接字
  int on = 1;
  setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(int));
  if (bind(server_fd, (sockaddr *)&server_addr, sizeof(server_addr)) == -1) {
    std::cerr << "Failed to bind socket: " << strerror(errno) << std::endl;
    close(server_fd);
    return -1;
  }

  // 监听套接字
  if (listen(server_fd, BACKLOG_SIZE) == -1) {
    std::cerr << "Failed to listen on socket: " << strerror(errno) << std::endl;
    close(server_fd);
    return -1;
  }

  std::cout << "Server started. Listening on port " << port << "..."
            << std::endl;

  // 接受一个连接
  client_fd = accept(server_fd, (sockaddr *)&server_addr, &addr_len);
  if (client_fd == -1) {
    std::cerr << "Failed to accept client connection: " << strerror(errno)
              << std::endl;
    close(server_fd);
    return -1;
  }
  int opt = 1;
  setsockopt(client_fd, IPPROTO_TCP, TCP_QUICKACK, (void *)&opt, sizeof(int));
  setsockopt(client_fd, IPPROTO_TCP, TCP_NODELAY, (void *)&opt, sizeof(int));

  // 关闭服务器套接字，因为我们只需要处理一个连接
  close(server_fd);

  std::cout << "New connection from " << inet_ntoa(server_addr.sin_addr) << ":"
            << ntohs(server_addr.sin_port) << std::endl;

  return client_fd;
}

int InitClient(const char *ip, int port) {
  int serv_fd = -1;
  struct sockaddr_in serv_addr {};

  // 创建 Socket 文件描述符
  serv_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (serv_fd < 0) {
    std::cerr << "Socket creation error: " << strerror(errno) << std::endl;
    return -1;
  }

  // 设置 Server 连接信息
  serv_addr.sin_family = AF_INET;
  serv_addr.sin_port = htons(port);
  // 将 ip 地址从文本转换为二进制格式
  if (inet_pton(AF_INET, ip, &serv_addr.sin_addr) <= 0) {
    std::cerr << "Invalid address/ Address not supported" << std::endl;
    close(serv_fd);
    return -1;
  }

  while (true) {
    if (connect(serv_fd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) ==
        -1) {
      std::cerr << "Connection to server failed: " << strerror(errno)
                << std::endl;
      sleep(1);
      continue;
    }
    std::cout << "Connection to server successful" << std::endl;
    // 设置套接字选项
    int opt = 1;
    if (setsockopt(serv_fd, IPPROTO_TCP, TCP_QUICKACK, (void *)&opt,
                   sizeof(int)) == -1) {
      std::cerr << "Failed to set TCP_QUICKACK option" << std::endl;
      close(serv_fd);
      return -1;
    }
    if (setsockopt(serv_fd, IPPROTO_TCP, TCP_NODELAY, (void *)&opt,
                   sizeof(int)) == -1) {
      std::cerr << "Failed to set TCP_NODELAY option" << std::endl;
      close(serv_fd);
      return -1;
    }
    break;
  }

  return serv_fd;
}

int senddata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len) {
  return send(send_sockfd, buf, len, 0);
}

// 发送数据
int send_buf(int fd, unsigned char *buf, uint64_t len) {
  size_t act_send_len;
  size_t tmp_send_len = 0;
  while (tmp_send_len < len) {
    act_send_len = send(fd, buf + tmp_send_len, len - tmp_send_len, 0);
    if (act_send_len == -1) {
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        // 数据暂时无法发送，稍后重试
        usleep(1000);  // 可以根据具体情况调整等待时间
        continue;
      }
      perror("net_send error");
      printf("error: act_send_len <= 0 in write_to_other_party\n");
      return -1;
    } else if (act_send_len == 0) {
      printf("Connection closed by peer.\n");
      return -1;
    }
    tmp_send_len += act_send_len;
  }
  return 0;
}

int recvdata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len) {
  ssize_t nread;
  ssize_t tmp_read_len = 0;
  uint64_t remain_read_len = *len;

  while (remain_read_len > 0) {
    nread = read(recv_sockfd, buf + tmp_read_len, *len - tmp_read_len);
    if (nread == 0) {
      if (tmp_read_len == *len) {
        break;
      }
      printf("socket shut down %s\n", strerror(errno));
      return -1;
    }
    if (nread < 0) {
      if (EINTR == errno || EAGAIN == errno) {
        continue;
      } else {
        printf("[%s] socket error\n", strerror(errno));
        return nread;
      }
    }
    tmp_read_len += nread;
    remain_read_len -= nread;
  }
  return *len;
}

void close_socket() {
  close(send_sockfd);
  close(recv_sockfd);
}

int ExecSingleInputOperator(DG_AlgorithmsType type, std::string inputFileName,
                            void *teeCfg, int nodeId) {
  if (type != ASCEND_SORT && type != DESCEND_SORT && type != SUM &&
      type != AVG ) {
    printf("operator type is not supported, required single input.\n");
    return -1;
  }
  printf("---------DG_InitPsiOpts------------\n");
  DG_Arithmetic_Opts aritOpts = DG_InitArithmeticOpts();

  printf("---------initTeeCtx------------\n");
  struct DG_TeeCtx *dgTee = nullptr;
  int rv = aritOpts.initTeeCtx(teeCfg, &dgTee);
  if (rv != 0) {
    printf("tee init error.-%d\n", rv);
    return rv;
  }
  printf("---------setTeeNodeInfos------------\n");
  struct TeeNodeInfo teeNodes[2];
  teeNodes[0].nodeId = 0;
  teeNodes[1].nodeId = 1;
  struct TeeNodeInfos allNodes;
  allNodes.nodeInfo = teeNodes;
  allNodes.size = 2;
  rv = aritOpts.setTeeNodeInfos(dgTee, &allNodes);
  if (rv != 0) {
    printf("tee set node info error.-%d\n", rv);
    return rv;
  }

  std::ifstream ifStream(inputFileName);
  int size = 0;
  std::string line;
  std::vector<std::string> datas;
  while (std::getline(ifStream, line)) {
    datas.push_back(line);
  }

  std::unique_ptr<double[]> inData = std::make_unique<double[]>(datas.size());
  for (int i = 0; i < datas.size(); i++) {
    inData[i] = (std::stod(datas[i].c_str())) * 1.0;
  }
  DG_TeeInput teeInput;
  teeInput.data.doubleNumbers = inData.get();
  teeInput.size = static_cast<int>(datas.size());
  teeInput.dataType = MPC_DOUBLE;
  printf("++++++++++input data size:%lu\n", teeInput.size);

  int res = aritOpts.negotiateSeeds(dgTee);
  printf("exchange seed res = %d\n", res);

  std::unique_ptr<DG_MpcShare[]> share = std::make_unique<DG_MpcShare[]>(2);
  DG_MpcShare *share1 = nullptr;
  DG_TeeOutput *output = nullptr;
  std::unique_ptr<DG_MpcShareSet> shares = std::make_unique<DG_MpcShareSet>();
  shares->size = SINGLEOP_SHRESET_SIZE;  // single input
  std::unique_ptr<DG_MpcShare[]> share_datas =
      std::make_unique<DG_MpcShare[]>(SINGLEOP_SHRESET_SIZE);
  if (nodeId == 0) {
    res = aritOpts.makeShare(dgTee, 1, nullptr, &share1);  // &teeInput
    if (res != DG_SUCCESS) {
      printf("recv share data error!. [ret=%d]\n", res);
    }
    sleep(1);
    share_datas[0] = *share1;
    shares->shareSet = share_datas.get();

  } else {  // node 1
    res = aritOpts.makeShare(dgTee, 0, &teeInput, &share1);
    if (res != DG_SUCCESS) {
      printf("1 make share self shar data fail.[ret=%d]\n", res);
      return res;
    }
    share_datas[0] = *share1;
    shares->shareSet = share_datas.get();
  }
  DG_MpcShare *share_out = nullptr;
  uint64_t start = GetCurrentTimestampMs();
  res = aritOpts.calculate(dgTee, type, shares.get(), &share_out);
  std::cout << "executeArithmeticOpts(ms):" << GetCurrentTimestampMs() - start
            << std::endl;
  if (res != DG_SUCCESS) {
    printf("executeArithmeticOpts error!.[ret=%d]\n", res);
    return res;
  }
  res = aritOpts.revealShare(dgTee, share_out, &output);
  printf("reveal res = %d\n", res);
  if (nodeId == 0) {
    int data_size = share_datas[0].size;
    std::vector<int64_t> fxp_datas0(data_size);
    for (int i = 0; i < data_size; i++) {
      fxp_datas0[i] =
          static_cast<int64_t>(share_datas[0].dataShare[i].shares[0] +
                               share_datas[0].dataShare[i].shares[1]);
    }
    std::cout << "input 0 fixpoint numbers: ";  // 打印输入转换成的定点数
    for (int i = 0; i < data_size; i++) {
      std::cout << fxp_datas0[i] << " ";
    }
    std::cout << "\n";

    std::cout
        << "input 0 fxp numbers -> double numbers: ";  // 打印输入转换后的定点数对应的double
    for (int i = 0; i < data_size; i++) {
      double tmp = fxp_datas0[i] * 1.0 / (1 << FXP_BITS);
      std::cout << tmp << " ";
    }
    std::cout << "\n";

    std::cout
        << "kcal compute result shares (fxp): ";  // 打印计算结果 share_out
                                                  // 恢复的定点数
    for (int i = 0; i < share_out->size; i++) {
      int64_t tmp = static_cast<int64_t>(share_out->dataShare[i].shares[0] +
                                         share_out->dataShare[i].shares[1]);
      std::cout << tmp << " ";
    }
    std::cout << "\n";
    std::cout << "kcal compute revealed result (double): ";  // 打印reveal的结果
                                                             // (double类型)
    for (int i = 0; i < share_out->size; i++) {
      std::cout << output->data.doubleNumbers[i] << " ";
    }
    std::cout << "\n";
  }
  aritOpts.releaseTeeCtx(&dgTee);
  aritOpts.releaseOutput(&output);
  return res;
}

void ExecutNet(DG_AlgorithmsType type, std::vector<std::string> data) {
  int send_port = (int)std::atoi(data[0].data());
  int recv_port = (int)std::atoi(data[1].data());
  std::cout << "send_port = " << send_port << " recv_port = " << recv_port
            << std::endl;
  int nodeId = std::atoi(data[2].data());
  std::string inputFileName = data[3];
  int firstSer = std::atoi(data[4].data());
  // 发送数据的Ip
  std::string sendIp = data[5];
  // 接收数据的Ip
  std::string recvIp = data[6];
  if (firstSer == 0) {
    std::future<int> recvFuture = std::async(InitServer, send_port);
    recv_sockfd = recvFuture.get();
    std::future<int> sendFuture =
        std::async(InitClient, recvIp.data(), recv_port);
    send_sockfd = sendFuture.get();
    sleep(5);
    CallMpcTee(type, nodeId, inputFileName);
  } else {
    std::future<int> sendFuture =
        std::async(InitClient, recvIp.data(), recv_port);
    send_sockfd = sendFuture.get();
    std::future<int> recvFuture = std::async(InitServer, send_port);
    recv_sockfd = recvFuture.get();
    sleep(5);
    CallMpcTee(type, nodeId, inputFileName);
  }
  sleep(10);
  close_socket();
}
void WriteMpcTeeLog(int level, const char *modelName, const char *filePathName,
                    int lineNum, const char *logStr) {
  auto t = std::time(nullptr);  // 获取当前时间
  auto localTime = std::localtime(&t);
  std::ostringstream oss;
  oss << std::put_time(localTime, "%Y-%m-%d %H:%M:%S");
  printf("%s %d [%s:%d][%s] %s\n", oss.str().c_str(), level, filePathName,
         lineNum, modelName, logStr);
}

void PrintfDGLog(void) {
  static DG_Callback registerLogger;
  registerLogger.writeLogCallback = WriteMpcTeeLog;
  int res = DG_RegisterCallback(&registerLogger);
  printf("register log:res=%d\n", res);
}

int CallMpcTee(DG_AlgorithmsType type, int nodeId, std::string inputFileName) {
  PrintfDGLog();
  printf("---------DG_InitConfigOpts------------\n");
  DG_ConfigOpts *opts = nullptr;
  int rv = DG_InitConfigOpts(DG_BusinessType::MPC, &opts);
  if (rv != 0) {
    printf("DG_InitConfigOpts error!code:%d\n", rv);
    return rv;
  }

  printf("---------Build_Config------------\n");
  void *teeCfg = NULL;
  rv = opts->init(&teeCfg);
  if (rv != 0) {
    printf(" opts->init(dgCfg)!-%d\n", rv);
    return rv;
  }
  opts->setIntValue(teeCfg, DG_CON_MPC_TEE_INT_NODEID, nodeId);
  opts->setIntValue(teeCfg, DG_CON_MPC_TEE_INT_FXP_BITS, FXP_BITS);
  opts->setIntValue(teeCfg, DG_CON_MPC_TEE_INT_THREAD_COUNT, 16);

  TEE_NET_RES teeNet = {senddata, recvdata};
  DG_Void netFunc;
  netFunc.data = &teeNet;
  netFunc.size = sizeof(TEE_NET_RES);
  opts->setVoidValue(teeCfg, DG_CON_MPC_TEE_VOID_NET_API, &netFunc);

  DG_TeeOutput *output = nullptr;
  int res;
  if (type == ASCEND_SORT || type == DESCEND_SORT || type == SUM ||
      type == AVG || type == MIN || type == MAX) {
    res = ExecSingleInputOperator(type, inputFileName, teeCfg, nodeId);
  } else {
    res = ExecArithmetic(type, inputFileName, teeCfg, nodeId);
  }
  DG_ReleaseConfigOpts(&opts);
  return 0;
}
