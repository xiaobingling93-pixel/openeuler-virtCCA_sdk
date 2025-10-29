# KCAL 中间件适配蚂蚁 scql 项目

本文档介绍 KCAL 中间件如何在 virtCCA 内部部署已经适配了的蚂蚁 scql 项目（`tag: 0.9.3b1` 版本）

## 前置条件
1. 需获取 `kcal` 包，含 `include`和`lib`目录，获取链接: [https://www.hikunpeng.com/developer/download](https://www.hikunpeng.com/developer/download)
2. 需要`bazel`编译构建工具，编译环境依赖参考: [devtools/dockerfiles/release-ci-aarch64.DockerFile at main · secretflow/devtools](https://github.com/secretflow/devtools/blob/main/dockerfiles/release-ci-aarch64.DockerFile)
3. 运行环境为`virtCCA cvm，前提是用户已经启动两个 virtCCA 的机密虚机（cvm1、cvm2）`

## 中间件使能和部署步骤

### 宿主机编译蚂蚁 scql 项目
1. 创建工作目录

   为方便进行演示，以下操作均以`/home/admin/dev/`目录作为工作主目录

2. clone virtCCA_sdk 仓

   ```bash
   cd /home/admin/dev
   git clone https://gitee.com/openeuler/virtCCA_sdk.git
   ```

3. clone 蚂蚁 scql 仓，应用 patch

   ```bash
   cd /home/admin/dev
   
   # clone 0.9.3b1 tag 的代码
   git clone --branch "0.9.3b1" https://github.com/secretflow/scql.git
   cd scql && git switch -c local
   
   # 应用 patch
   git apply /home/admin/dev/virtCCA_sdk/MPC/third_party_adaptor/secrerflow/scql/patches/kcal.patch
   ```

4. 引入中间件和 kcal 库

   ```bash
   # 假设 kcal 库已下载解压在 /opt/kcal 目录下
   cp -r /opt/kcal/include /home/admin/dev/scql/engine/third_party/kcal/
   cp -r /opt/kcal/lib /home/admin/dev/scql/engine/third_party/kcal/
   
   # 引入中间件
   cp -r /home/admin/dev/virtCCA_sdk/MPC/middleware /home/admin/dev/scql/engine/third_party/kcal_middleware
   ```

5. 编译

   ```bash
   cd /home/admin/dev/scql
   
   # -DEXECUTE_IN_KCAL, 该宏为使能 kcal 加速库
   bazel build //engine/exe:scqlengine -c opt --copt=-DEXECUTE_IN_KCAL --define disable_tcmalloc=true
   
   # 创建临时目录 bin，存放 scqlengine 可执行文件
   mkdir bin; cp ./bazel-bin/engine/exe/scqlengine ./bin/
   ```

### scqlengine 部署至 virtCCA 内

保持和蚂蚁 `scql` 仓库的 `p2p-tutorial` 下面的`engine_alice`和`engine_bob`容器内目录一致

+ 进入到`scql`项目目录下，`cd scql`，所有操作在此目录下

+ 先初始化`scql`的`examples/p2p-tutorial`

  参考：[https://www.secretflow.org.cn/zh-CN/docs/scql/0.9.3b1/intro/p2p-tutorial](https://www.secretflow.org.cn/zh-CN/docs/scql/0.9.3b1/intro/p2p-tutorial)

  完成示例工程的初始化，后续基于这个配置进行测试

+ 修改示例工程的相关配置文件

  1. `examples/p2p-tutorial/broker/alice/conf/config.yml`

     替换实际的部署`virtCCA`机器的ip，\<virtCCA engine alice ip\>

     ```yaml
     intra_server:
       protocol: http
       host: 0.0.0.0
       port: 8080
     inter_server:
       port: 8081
       protocol: https
       cert_file: "/home/admin/tls/cert.crt"
       key_file: "/home/admin/tls/key.key"
     log_level: debug
     party_code: alice
     party_info_file: "/home/admin/configs/party_info.json"
     private_key_path: "/home/admin/configs/private_key.pem"
     intra_host: broker_alice:8080
     engine:
       timeout: 120s
       protocol: https
       content_type: application/json
       uris:
         - for_peer: <virtCCA engine alice ip>:8004
           for_self: <virtCCA engine alice ip>:8003
     storage:
       type: mysql
       conn_str: "root:__MYSQL_ROOT_PASSWD__@tcp(mysql:3306)/brokeralice?charset=utf8mb4&parseTime=True&loc=Local&interpolateParams=true"
       max_idle_conns: 10
       max_open_conns: 100
       conn_max_idle_time: 2m
       conn_max_lifetime: 5m
     ```

  2. `examples/p2p-tutorial/broker/bob/conf/config.yml`

     替换实际的部署`virtCCA`机器的ip，\<virtCCA engine bob ip>

     ```json
     intra_server:
       protocol: http
       host: 0.0.0.0
       port: 8080
     inter_server:
       port: 8081
       protocol: https
       cert_file: "/home/admin/tls/cert.crt"
       key_file: "/home/admin/tls/key.key"
     log_level: debug
     party_code: bob
     party_info_file: "/home/admin/configs/party_info.json"
     private_key_path: "/home/admin/configs/private_key.pem"
     intra_host: broker_bob:8080
     engine:
       timeout: 120s
       protocol: https
       content_type: application/json
       uris:
         - for_peer: <virtCCA engine bob ip>:8004
           for_self: <virtCCA engine bob ip>:8003
     storage:
       type: mysql
       conn_str: "root:__MYSQL_ROOT_PASSWD__@tcp(mysql:3306)/brokerbob?charset=utf8mb4&parseTime=True&loc=Local&interpolateParams=true"
       max_idle_conns: 10
       max_open_conns: 100
       conn_max_idle_time: 2m
       conn_max_lifetime: 5m
     ```

  3. `examples/p2p-tutorial/engine/alice/conf/gflags.conf` 和`examples/p2p-tutorial/engine/bob/conf/gflags.conf`

     下面给出修改部分位置，其他内容保持不变

     ```bash
     # alice 下的配置文件修改 mysql 的 host ip 为宿主机 ip <parent host>
     --embed_router_conf={"datasources":[{"id":"ds001","name":"mysql db","kind":"MYSQL","connection_str":"db=alice;user=root;password=__MYSQL_ROOT_PASSWD__;host=<parent host>;auto-reconnect=true"}],"rules":[{"db":"*","table":"*","datasource_id":"ds001"}]}
     
     # bob 下的配置文件修改 mysql 的 host ip 为宿主机 ip <parent host>
     --embed_router_conf={"datasources":[{"id":"ds001","name":"mysql db","kind":"MYSQL","connection_str":"db=alice;user=root;password=__MYSQL_ROOT_PASSWD__;host=mysql;auto-reconnect=true"}],"rules":[{"db":"*","table":"*","datasource_id":"ds001"}]}
     ```

+ 部署 mysql 和 broker

  这里直接将`broker`和`mysql`部署在宿主机侧方便测试，修改原`docker-compose.yml`，删除`engine_alice`和`engine_bob`服务，这两个部署在`virtCCA`内

  ```yaml
  services:
    broker_alice:
      image: ${SCQL_IMAGE:-secretflow/scql:latest}
      command:
        - /home/admin/bin/broker
        - -config=/home/admin/configs/config.yml
      restart: always
      ports:
        - mode: host
          protocol: tcp
          published: ${ALICE_PORT:-8081}
          target: 8080
      volumes:
        - ./broker/alice/conf/:/home/admin/configs/
        - ./tls/root-ca.crt:/etc/ssl/certs/root-ca.crt
        - ./tls/broker_alice-ca.crt:/home/admin/tls/cert.crt
        - ./tls/broker_alice-ca.key:/home/admin/tls/key.key
    broker_bob:
      image: ${SCQL_IMAGE:-secretflow/scql:latest}
      command:
        - /home/admin/bin/broker
        - -config=/home/admin/configs/config.yml
      restart: always
      ports:
        - mode: host
          protocol: tcp
          published: ${BOB_PORT:-8082}
          target: 8080
      volumes:
        - ./broker/bob/conf/:/home/admin/configs/
        - ./tls/root-ca.crt:/etc/ssl/certs/root-ca.crt
        - ./tls/broker_bob-ca.crt:/home/admin/tls/cert.crt
        - ./tls/broker_bob-ca.key:/home/admin/tls/key.key
    mysql:
      image: mysql:8.0.39
      environment:
        - MYSQL_ROOT_PASSWORD=__MYSQL_ROOT_PASSWD__
        - TZ=Asia/Shanghai
      healthcheck:
        retries: 10
        test:
          - CMD
          - mysqladmin
          - ping
          - -h
          - mysql
        timeout: 20s
      ports:
        - "3306:3306"
      expose:
        - "3306"
      restart: always
      volumes:
        - ./mysql/initdb:/docker-entrypoint-initdb.d
  ```

+ 执行下面脚本，完成`scqlengine`的部署

  ```bash
  #!/bin/bash
  set -e
  
  cur_dir=$(cd $(dirname "$0") && pwd) && cd $cur_dir
  
  sender_ip="xxx.xxx.xxx.xxx"
  receiver_ip="xxx.xxx.xxx.xxx"
  work_dir="/home/admin"
  
  chmod +x ${cur_dir}/bin/*
  
  ssh -t root@${sender_ip} "mkdir -p /home/admin/bin /home/admin/engine/conf /home/admin/tls /home/admin/lib"
  ssh -t root@${receiver_ip} "mkdir -p /home/admin/bin /home/admin/engine/conf /home/admin/tls /home/admin/lib"
  
  LIB_FILES=(
    /opt/kcal/lib/libdata_guard_common.so
    /opt/kcal/lib/libdata_guard.so
    /opt/kcal/lib/libhitls_bsl.so
    /opt/kcal/lib/libhitls_crypto.so
    /opt/kcal/lib/libmpc_tee.so
    /opt/kcal/lib/libsecurec.so
  )
  
  # engine alice 部署
  scp ${cur_dir}/bin/scqlengine root@${sender_ip}:${work_dir}/bin/
  scp ${cur_dir}/examples/p2p-tutorial/engine/alice/conf/gflags.conf root@${sender_ip}:${work_dir}/engine/conf/gflags.conf
  scp ${cur_dir}/examples/p2p-tutorial/tls/engine_alice-ca.crt root@${sender_ip}:${work_dir}/engine/conf/cert.crt
  scp ${cur_dir}/examples/p2p-tutorial/tls/engine_alice-ca.key root@${sender_ip}:${work_dir}/engine/conf/key.key
  # engine bob 部署
  scp ${cur_dir}/bin/scqlengine root@${receiver_ip}:${work_dir}/bin/
  scp ${cur_dir}/examples/p2p-tutorial/engine/bob/conf/gflags.conf root@${receiver_ip}:${work_dir}/engine/conf/gflags.conf
  scp ${cur_dir}/examples/p2p-tutorial/tls/engine_bob-ca.crt root@${receiver_ip}:${work_dir}/engine/conf/cert.crt
  scp ${cur_dir}/examples/p2p-tutorial/tls/engine_bob-ca.key root@${receiver_ip}:${work_dir}/engine/conf/key.key
  # kcal *.so
  for file in ${LIB_FILES[*]}; do
    scp ${file} root@${sender_ip}:${work_dir}/lib/
    scp ${file} root@${receiver_ip}:${work_dir}/lib/
  done
  ```

+ 分别进入部署了`engine_alice`和`engine_bob`的`cvm`内，拉起各自的服务

  ```bash
  # alice 执行
  LD_LIBRARY_PATH=/home/admin/lib /home/admin/bin/scqlengine --flagfile=/home/admin/engine/conf/gflags.conf
  # bob 执行
  LD_LIBRARY_PATH=/home/admin/lib /home/admin/bin/scqlengine --flagfile=/home/admin/engine/conf/gflags.conf
  ```

## 测试

可以参考`宿主机编译蚂蚁 scql 项目`进行构建不使能的`scql`代码

```bash
cd /home/admin/dev/scql

# -DEXECUTE_IN_KCAL, 该宏为使能 kcal 加速库
bazel build //engine/exe:scqlengine -c opt --define disable_tcmalloc=true
```

> 由于拉起`mysql`服务时，自带了一些数据，这里不生成假数据，直接进行测试

1. 初始化项目

   参考：[https://www.secretflow.org.cn/zh-CN/docs/scql/0.9.3b1/intro/p2p-tutorial](https://www.secretflow.org.cn/zh-CN/docs/scql/0.9.3b1/intro/p2p-tutorial)

   + 这里修改教程第一步`create project`命令，以及后面授权 CCL`grant xxx` 命令，其它保持不变

   ```bash
   # 创建工程修改
   ./brokerctl create project --project-id "demo" --project-conf '{"spu_runtime_cfg":{"protocol":"SEMI2K","field":"FM64","fxp_fraction_bits":"10","max_concurrency":"16"},"session_expire_seconds":"86400"}' --host http://localhost:8081
   
   # CCL 授权调整
   # alice set CCL for table ta
   ./brokerctl grant alice PLAINTEXT --project-id "demo" --table-name ta --column-name ID --host http://localhost:8081
   ./brokerctl grant alice PLAINTEXT --project-id "demo" --table-name ta --column-name credit_rank --host http://localhost:8081
   ./brokerctl grant alice PLAINTEXT --project-id "demo" --table-name ta --column-name income --host http://localhost:8081
   ./brokerctl grant alice PLAINTEXT --project-id "demo" --table-name ta --column-name age --host http://localhost:8081
   
   ./brokerctl grant bob PLAINTEXT_AFTER_JOIN --project-id "demo" --table-name ta --column-name ID --host http://localhost:8081
   ./brokerctl grant bob PLAINTEXT_AFTER_AGGREGATE --project-id "demo" --table-name ta --column-name credit_rank --host http://localhost:8081
   ./brokerctl grant bob PLAINTEXT_AFTER_COMPARE --project-id "demo" --table-name ta --column-name income --host http://localhost:8081
   ./brokerctl grant bob PLAINTEXT --project-id "demo" --table-name ta --column-name age --host http://localhost:8081
   # bob set ccl for table tb
   ./brokerctl grant bob PLAINTEXT --project-id "demo" --table-name tb --column-name ID --host http://localhost:8082
   ./brokerctl grant bob PLAINTEXT --project-id "demo" --table-name tb --column-name order_amount --host http://localhost:8082
   ./brokerctl grant bob PLAINTEXT --project-id "demo" --table-name tb --column-name is_active --host http://localhost:8082
   
   ./brokerctl grant alice PLAINTEXT_AFTER_JOIN --project-id "demo" --table-name tb --column-name ID --host http://localhost:8082
   ./brokerctl grant alice PLAINTEXT_AFTER_AGGREGATE --project-id "demo" --table-name tb --column-name is_active --host http://localhost:8082
   ./brokerctl grant alice PLAINTEXT_AFTER_COMPARE --project-id "demo" --table-name tb --column-name order_amount --host http://localhost:8082
   ```
   
2. 执行查询
   
这里只是演示使能`kcal`后的效果，正确性对比可以去掉`kcal`的使能然后替换`virtCCA`内部的`scqlengine`重新执行下面的`sql`语句，输出结果保持一致
   
```bash
./brokerctl run "SELECT (ta.income + tb.order_amount) < tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT (ta.income - tb.order_amount) < tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT (ta.income * tb.order_amount) < tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT (ta.income / tb.order_amount) < tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income < tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income <= tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income > tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income >= tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income = tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT ta.income <> tb.order_amount FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT SUM(ta.credit_rank * tb.is_active) AS sum FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT AVG(ta.credit_rank * tb.is_active) AS avg FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT MAX(ta.credit_rank * tb.is_active) AS max FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
./brokerctl run "SELECT MIN(ta.credit_rank * tb.is_active) AS min FROM ta INNER JOIN tb ON ta.ID = tb.ID;"  --project-id "demo" --host http://localhost:8081 --timeout 300
```
   
   
   
   
   
   
   
   
   
   
   
   
   
   
   
   
   
   
   