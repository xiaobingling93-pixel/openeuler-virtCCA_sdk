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
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <memory>
#include <iostream>
#include <netinet/tcp.h>
#include <future>
#include <fstream>
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include "data_guard_mpc.h"

#define PORT 8080
#define BUFFER_SIZE 1024
#define BACKLOG_SIZE 16  // 请求队列最大长度
#define SLEEP_FIVE 5
#define NODES_SIZE 2

int g_sendSockfd = -1;
int g_recvSockfd = -1;

int CallMpcTee(int nodeId, std::string inputFileName, std::string sendIp, std::string recvIp, short port1, short port2);
int senddata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len);
int recvdata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len);
void CloseSocket();
int InitServer(int port);
int InitClient(const char *ip, int port);

void BuildDgString(std::vector<std::string> &strings, DG_String **dg, unsigned int &size)
{
    size = strings.size();
    DG_String *dgString = new DG_String[strings.size()];
    for (size_t i = 0; i < strings.size(); i++) {
        dgString[i].str = strdup(strings[i].c_str());
        dgString[i].size = strings[i].size() + 1;
    }
    *dg = dgString;
}

void ReleaseDgString(DG_String *dg, unsigned int size)
{
    for (size_t i = 0; i < size; i++) {
        free(dg[i].str);
    }
    delete[] dg;
}

TeeNodeInfos BuildTeeNodeInfos(short port1, short port2)
{
    struct TeeNodeInfo teeNodes[NODES_SIZE];
    teeNodes[0].nodeId = 0;
    teeNodes[1].nodeId = 1;
    struct TeeNodeInfos allNodes;
    allNodes.nodeInfo = teeNodes;
    allNodes.size = NODES_SIZE;
    return allNodes;
}

int main(int argc, char **argv)
{
    if (typeid(uint64_t) == typeid(unsigned long long)) {
        std::cout << "uint64_t is equivalent to unsigned long long." << std::endl;
    } else {
        std::cout << "uint64_t is NOT equivalent to unsigned long long." << std::endl;
    }

    int sizeUll = sizeof(unsigned long long) * 8;

    std::cout << "Size of unsigned long long: " << sizeUll << " bits" << std::endl;
    std::cout << "Size of uint64: " << sizeUll << " bits" << std::endl;
    if (argc < 7) {
        printf("params: send port, recv port, current nodeId, inputfileName, firstserver,\n");
        exit(-1);
    }

    int sendPort = (int) std::atoi(argv[1]);
    int recvPort = (int) std::atoi(argv[2]);
    int nodeId = std::atoi(argv[3]);
    std::string inputFileName = argv[4];
    TeeNodeInfos teeNodeInfo{};
    // firstSer 谁先启动，0表示先启动
    int firstSer = std::atoi(argv[5]);
        // 发送数据的Ip
    std::string sendIp = argv[6];
    // 接收数据的Ip
    std::string recvIp = argv[7];

    if (firstSer == 0) {
        std::future<int> recvFuture = std::async(InitServer, sendPort);
        g_recvSockfd = recvFuture.get();
        std::future<int> sendFuture = std::async(InitClient, recvIp.data(), recvPort);
        g_sendSockfd = sendFuture.get();
        sleep(SLEEP_FIVE);
        CallMpcTee(nodeId, inputFileName, sendIp, recvIp, sendPort, recvPort);
    } else {
        std::future<int> sendFuture = std::async(InitClient, recvIp.data(), recvPort);
        g_sendSockfd = sendFuture.get();
        std::future<int> recvFuture = std::async(InitServer, sendPort);
        g_recvSockfd = recvFuture.get();
        sleep(SLEEP_FIVE);
        CallMpcTee(nodeId, inputFileName, recvIp, sendIp, recvPort, sendPort);
    }

    sleep(SLEEP_FIVE);
    CloseSocket();
    return 0;
}

static int64_t GetCurrentTimestampMs()
{
    auto now = std::chrono::system_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch());
    return duration.count() / 1000;
}


int CallMpcTee(int nodeId, std::string inputFileName, std::string sendIp, std::string recvIp, short port1, short port2)
{
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
    opts->setIntValue(teeCfg, DG_CON_MPC_TEE_INT_FXP_BITS, 8);
    opts->setIntValue(teeCfg, DG_CON_MPC_TEE_INT_THREAD_COUNT, 16);

    TEE_NET_RES teeNet = {senddata, recvdata};
    DG_Void netFunc;
    netFunc.data = &teeNet;
    netFunc.size = sizeof(TEE_NET_RES);
    opts->setVoidValue(teeCfg, DG_CON_MPC_TEE_VOID_NET_API, &netFunc);

    printf("---------DG_InitTeeMpcOpts------------\n");
    DG_PrivateSet_Opts teeOpts = DG_InitPsiOpts();

    printf("---------initTeeMpcSql------------\n");
    struct DG_TeeCtx *dgTee = nullptr;
    rv = teeOpts.initTeeCtx(teeCfg, &dgTee);
    if (rv != 0) {
        printf("tee init error.-%d\n", rv);
        return rv;
    }
    printf("---------setTeeNodeInfos------------\n");
    struct TeeNodeInfo teeNodes[NODES_SIZE];
    teeNodes[0].nodeId = 0;
    teeNodes[1].nodeId = 1;
    struct TeeNodeInfos allNodes;
    allNodes.nodeInfo = teeNodes;
    allNodes.size = NODES_SIZE;
    rv = teeOpts.setTeeNodeInfos(dgTee, &allNodes);
    if (rv != 0) {
        printf("tee set node info error.-%d\n", rv);
        return rv;
    }
    printf("---------executePrivateSetOpts------------\n");
    std::ifstream ifStream(inputFileName);
    std::string line;
    std::vector<std::string> datas;
    while (std::getline(ifStream, line)) {
        datas.push_back(line);
    }
    unsigned int size;
    DG_String *strings = nullptr;
    BuildDgString(datas, &strings, size);
    DG_TeeInput teeInput;
    teeInput.data.strings = strings;
    teeInput.size = size;
    teeInput.dataType = MPC_STRING;
    printf("++++++++++input data size:%lu\n", teeInput.size);

    DG_TeeOutput *output = nullptr;
    uint64_t start = GetCurrentTimestampMs();
    int res = teeOpts.calculate(dgTee, PSI, &teeInput, &output, TEE_OUTPUT_INDEX);
    printf("total time:%lu\n", GetCurrentTimestampMs() - start);
    if (res != 0 || output == nullptr) {
        printf("calc psi result:%d\n", res);
        return res;
    }

    int randomNumber = std::rand() % 100 + 10; // 生成 [1, 100] 范围内的随机数
    auto now = std::chrono::system_clock::now();
    // 将时间转化为自1970年1月1日以来的毫秒数
    auto duration = now.time_since_epoch();
    auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(duration).count();
    std::string outFile = "output-" + std::to_string(randomNumber) + std::to_string(timestamp) + \
        "-" + (nodeId == 0 ? "server" : "client") + ".csv";
    int outFp = open(outFile.c_str(), O_RDWR | O_CREAT);
    printf("++++++++++++++output:%lu\n", output->size);
    if (output->dataType == MPC_STRING) {
        for (int j = 0; j < output->size; j++) {
            std::string conent = std::string(output->data.strings[j].str) + "\n";
            write(outFp, conent.c_str(), conent.size());
        }
    } else {
        for (int j = 0; j < output->size; j++) {
            std::string conent = std::to_string(output->data.u64Numbers[j]) + "\n";
            write(outFp, conent.c_str(), conent.size());
        }
    }

    teeOpts.releaseOutput(&output);
    printf("release output:%d\n", res);
    teeOpts.releaseTeeCtx(&dgTee);
    DG_ReleaseConfigOpts(&opts);
    close(outFp);
    return 0;
}

int InitServer(int port)
{
    int serverFd = -1;
    int clientFd = -1;
    sockaddr_in serverAddr{};
    socklen_t addrLen = sizeof(serverAddr);

    // 创建服务器套接字
    serverFd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (serverFd == -1) {
        std::cerr << "Failed to create socket: " << strerror(errno)
                  << std::endl;
        return -1;
    }
    std::cout<<"port1 = "<<port<<std::endl;
    // 设置服务器地址
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_addr.s_addr = INADDR_ANY;
    serverAddr.sin_port = htons(port);
    std::cout<<"port2 = "<<port<<std::endl;
    // 绑定套接字
    int on = 1;
    setsockopt(serverFd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(int));
    if (bind(serverFd, (sockaddr *)&serverAddr, sizeof(serverAddr)) == -1) {
        std::cerr << "Failed to bind socket: " << strerror(errno) << std::endl;
        close(serverFd);
        return -1;
    }

    // 监听套接字
    if (listen(serverFd, BACKLOG_SIZE) == -1) {
        std::cerr << "Failed to listen on socket: " << strerror(errno)
                  << std::endl;
        close(serverFd);
        return -1;
    }

    std::cout << "Server started. Listening on port " << port << "..."
              << std::endl;

    // 接受一个连接
    clientFd = accept(serverFd, (sockaddr *)&serverAddr, &addrLen);
    if (clientFd == -1) {
        std::cerr << "Failed to accept client connection: " << strerror(errno)
                  << std::endl;
        close(serverFd);
        return -1;
    }
    int opt = 1;
    setsockopt(clientFd, IPPROTO_TCP, TCP_QUICKACK, (void *)&opt, sizeof(int));
    setsockopt(clientFd, IPPROTO_TCP, TCP_NODELAY, (void *)&opt, sizeof(int));

    // 关闭服务器套接字，因为我们只需要处理一个连接
    close(serverFd);

    std::cout << "New connection from " << inet_ntoa(serverAddr.sin_addr)
              << ":" << ntohs(serverAddr.sin_port) << std::endl;

    return clientFd;
}

int InitClient(const char *ip, int port)
{
    int servFd = -1;
    struct sockaddr_in servAddr{};

    // 创建 Socket 文件描述符
    servFd = socket(AF_INET, SOCK_STREAM, 0);
    if (servFd < 0) {
        std::cerr << "Socket creation error: " << strerror(errno) << std::endl;
        return -1;
    }

    // 设置 Server 连接信息
    servAddr.sin_family = AF_INET;
    servAddr.sin_port = htons(port);
    // 将 ip 地址从文本转换为二进制格式
    if (inet_pton(AF_INET, ip, &servAddr.sin_addr) <= 0) {
        std::cerr << "Invalid address/ Address not supported" << std::endl;
        close(servFd);
        return -1;
    }

    while (true) {
        if (connect(servFd, (struct sockaddr *)&servAddr,
                    sizeof(servAddr)) == -1) {
            std::cerr << "Connection to server failed: " << strerror(errno)
                      << std::endl;
            sleep(1);
            continue;
        }
        std::cout << "Connection to server successful" << std::endl;
        // 设置套接字选项
        int opt = 1;
        if (setsockopt(servFd, IPPROTO_TCP, TCP_QUICKACK, (void *)&opt,
                       sizeof(int)) == -1) {
            std::cerr << "Failed to set TCP_QUICKACK option" << std::endl;
            close(servFd);
            return -1;
        }
        if (setsockopt(servFd, IPPROTO_TCP, TCP_NODELAY, (void *)&opt,
                       sizeof(int)) == -1) {
            std::cerr << "Failed to set TCP_NODELAY option" << std::endl;
            close(servFd);
            return -1;
        }
        break;
    }

    return servFd;
}

int senddata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len)
{
    return send(g_sendSockfd, buf, len, 0);
}

int recvdata(struct TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len)
{
    ssize_t nread;
    ssize_t tmpReadLen = 0;
    uint64_t remainReadLen = *len;

    while (remainReadLen > 0) {
        nread = read(g_recvSockfd, buf + tmpReadLen, *len - tmpReadLen);
        if (nread == 0) {
            printf("socket shut down\n");
            return 0;
        }
        if (nread < 0) {
            if (EINTR == errno || EAGAIN == errno) {
                continue;
            } else {
                printf("[%s] socket error\n", strerror(errno));
                return nread;
            }
        }
        tmpReadLen += nread;
        remainReadLen -= nread;
    }
    return *len;
}

void CloseSocket()
{
    close(g_sendSockfd);
    g_sendSockfd = NULL;
    close(g_recvSockfd);
    g_recvSockfd = NULL;
}
