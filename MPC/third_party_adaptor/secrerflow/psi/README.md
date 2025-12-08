# KCAL 中间件适配蚂蚁 psi 库

本文档介绍 KCAL 中间件如何在 virtCCA 内部署已经适配了的蚂蚁 psi 库（`tag: psi-v0.6.0.dev250507` 版本）

## 前置条件

1. 需获取 `kcal` 包，含 `include` 和 `lib` 目录，获取链接：[https://support.huawei.com/enterprise/zh/software/265814201-ESW2001490913](https://support.huawei.com/enterprise/zh/software/265814201-ESW2001490913)
2. 需要 bazel 编译构建工具，编译环境依赖参考：[devtools/dockerfiles/release-ci-aarch64.DockerFile at main · secretflow/devtools](https://github.com/secretflow/devtools/blob/main/dockerfiles/release-ci-aarch64.DockerFile)
3. 运行环境为`virtCCA cvm，前提是用户已经启动两个 virtCCA 的机密虚机（cvm1、cvm2）`​

## 中间件使能和部署步骤

### 宿主机编译蚂蚁 psi 库

1. 创建工作目录

    为方便进行演示，以下操作均以 `/home/admin/dev` 目录作为工作主目录

2. clone virtCCA\_sdk 仓

    ```bash
    cd /home/admin/dev

    git clone https://gitee.com/openeuler/virtCCA_sdk.git
    ```

3. clone 蚂蚁 psi 仓，应用 patch

    ```bash
    cd /home/admin/dev

    # clone 仓库，并创建一个本地分支
    git clone --branch "v0.6.0.dev250507" https://github.com/secretflow/psi.git

    # 进到蚂蚁 psi 目录下
    cd /home/admin/dev/psi
    git switch -c kcal-on-v0.6.0

    # 应用 virtCCA_sdk 下面的 patch
    git apply /home/admin/dev/virtCCA_sdk/MPC/third_party_adaptor/secrerflow/psi/patches/kcal.patch
    ```

4. 引入中间件和 kcal 库

    ```bash
    # 假设 kcal 库已下载在 /opt/kcal 目录下
    cp -r /opt/kcal/include /home/admin/dev/psi/third_party/kcal/
    cp -r /opt/kcal/lib /home/admin/dev/psi/third_party/kcal/

    # 引入中间件
    cp -r /home/admin/dev/virtCCA_sdk/MPC/middleware/* /home/admin/dev/psi/third_party/kcal_middleware/
    ```

5. 编译

    ```bash
    cd /home/admin/dev/psi
    # 编译完成后，在`bazel-bin/psi/apps/psi_launcher`目录下生成`main`可执行文件
    bazel build //... -c opt
    # 若提示比较时类型不同，可指定编译时不报错
    # bazel build //... --copt=-Wno-error=sign-compare -c opt

    # 创建临时目录 bin，存放 main 可执行文件
    mkdir bin
    cp ./bazel-bin/psi/apps/psi_launcher/main ./bin/main
    ```



### 部署至 virtCCA 内

可让`/home/admin/dev/psi`的目录结构与`virtCCA`内部保持一致，方便进行测试

```bash
# cvm 内创建目录
virsh console cvm
mkdir -p /home/admin/dev

# 宿主机内，拷贝蚂蚁 psi 编译后项目整体至 cvm 内
cd /home/admin/dev
tar -czvf psi.tar.gz psi
scp -r /home/admin/dev/psi.tar.gz root@<cvm ip>:/home/admin/dev/

# 进入 cvm 内，解压
virsh console cvm
cd /home/admin/dev && tar -xzvf psi.tar.gz
```

## KCAL 中间件适配蚂蚁 psi 库测试

### 测试数据准备

#### 宿主机侧数据生成

1. 进入`/home/admin/dev/psi`目录
2. PSI 算法数据生成

    步骤可参考：`examples/psi/README.md`​

    ```bash
    python examples/psi/generate_psi_data.py \
    		--receiver_item_cnt 1e6 \
            --sender_item_cnt 1e6 \
    		--intersection_cnt 8e4 \
    		--id_cnt 2 \
            --receiver_path /tmp/receiver_input.csv \
            --sender_path /tmp/sender_input.csv \
            --intersection_path /tmp/intersection.csv
    ```

    > 说明：
    >
    > --receiver_item_cnt：receiver 方拥有的数据总量
    >
    > --sender_item_cnt：sender 方拥有的数据总量
    >
    > --intersection_cnt：约定两方产生交集部分的数据总量
    >
    > --id_cnt：每个参与方的输入数据包含几个字段
    >
    > --receiver_path：receiver 方输入数据的文件位置
    >
    > --sender_path：sender 方输入数据的文件位置
    >
    > --intersection_path：生成的交集数据的文件位置
    >
3. PIR 算法数据生成

    步骤可参考：`examples/pir/README.md`​

    ```bash
    python examples/pir/apsi/test_data_creator.py \
    	   --sender_size=10000000 \
    	   --receiver_size=1000 \
           --intersection_size=100 \
           --label_byte_count=100 \
           --item_byte_count=16

    # 生成的用来最后比对结果的交集集合
    mv ground_truth.csv /tmp/ground_truth.csv
    # 数据库模拟数据
    mv db.csv /tmp/db.csv
    # 查询数据
    mv query.csv /tmp/query.csv
    ```

    > 说明：
    >
    > --sender_size：服务端数据库总体数据行数
    >
    > --receiver_size：客户端要查询的 key 的数量
    >
    > --intersection_size：实际上生成的数据里面，服务端只有 intersection_size 个包含客户端能够查到的键值
    >
    > --label_byte_count：服务端数据库每个 value 所占的字节数
    >
    > --item_byte_count：服务端数据库每个 key 所占的字节数
    >

#### 拷贝测试数据至 virtCCA 内

将 PSI PIR 的测试数据分别拷贝进两个 virtCCA 内

```bash
scp /tmp/receiver_input.csv \
	/tmp/sender_input.csv \
	/tmp/intersection.csv \
	/tmp/ground_truth.csv \
	/tmp/db.csv \
	/tmp/query.csv \
	root@<cvm ip>:/tmp/
```

### KCAL PSI 测试

#### 配置文件说明

配置文件已在`patch`中提供，只需修改下列说明的部分进行测试

下面以`kcal_sender.json`为例

```json
{
  "psi_config": {
    "protocol_config": {
      "protocol": "PROTOCOL_KCAL",
      "kcal_config": {
        "thread_count": 16,								// 线程数按需修改，目前固定 16 线程
		"use_sm_alg": false								// 是否启用国密算法
      },
      "role": "ROLE_SENDER",
      "broadcast_result": true
    },
    "input_config": {
      "type": "IO_TYPE_FILE_CSV",
      "path": "/tmp/sender_input.csv"					// 当前参与方运行 psi 算法的数据输入文件位置，按需修改
    },
    "output_config": {
      "type": "IO_TYPE_FILE_CSV",						// 文件类型不需修改
      "path": "/tmp/kcal_sender_output.csv"				// 两方运行完 psi 算法后，最终交集文件的输出位置，按需修改
    },
    "keys": ["id_0", "id_1"],                           // 有几个字段
    "debug_options": {									// 无需修改
      "trace_path": "/tmp/kcal_sender.trace"
    },
    "disable_alignment": true,
    "recovery_config": {								// 这个配置不需要修改，kcal 目前无 recovery 模式
      "enabled": false,
      "folder": "/tmp/kcal_sender_cache"
    }
  },
  "link_config": {
    "parties": [  										// 两个参与方的通信 ip 和 端口，按需修改
      {
        "id": "receiver",
        "host": "127.0.0.1:5300"
      },
      {
        "id": "sender",
        "host": "127.0.0.1:5400"
      }
    ]
  },
  "self_link_party": "sender"							// 当前参与方的标识
}

```

#### kcal 两个配置文件

- examples/psi/config/kcal_receiver.json
- examples/psi/config/kcal_sender.json

#### 蚂蚁对比配置文件

- examples/psi/config/rr22_receiver_recovery.json
- examples/psi/config/rr22_sender_recovery.json

#### 测试

进入两个 cvm 分别执行以下命令

```bash
cd /home/admin/dev/psi

# 参与方 receiver
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/path/to/kcal/lib ./bin/main --config $(pwd)/examples/psi/config/kcal_receiver.json
# 参与方 sender
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/path/to/kcal/lib ./bin/main --config $(pwd)/examples/psi/config/kcal_sender.json
```

运行完以上命令后，每个`cvm`内会在配置文件中指明的`output_config.path`路径中生成交集文件

#### 结果对比

将`/tmp/kcal_sender_output.csv`、`/tmp/kcal_receiver_output.csv`的内容与一开始生成的交集文件`/tmp/intersection.csv`内容进行比对，结果保持一致

### KCAL PIR 测试

编译完成后，进入`/home/admin/dev/psi`目录，步骤可参考：`examples/pir/README.md`​

#### 配置文件说明

配置文件已在`patch`中提供，只需修改下列说明的部分进行测试

```json
// 客户端配置文件
{
  "kcal_pir_receiver_config": {
    "threads": 16,									// 多线程处理，按需修改
    "query_file": "/tmp/query.csv",					// 要查询的 key 的集合文件位置，按需修改
    "output_file": "/tmp/result.csv",				// 查询结果 value 的保存位置，按需修改
    "is_dummy_mode": true,							// 查询的 key 是否进行 dummy，按需修改
	"use_sm_alg": false								// 是否启用国密算法
  },
  "link_config": {									// 两个参与方的通信 ip 和 端口，按需修改
    "parties": [
      {
        "id": "sender",
        "host": "127.0.0.1:5300"
      },
      {
        "id": "receiver",
        "host": "127.0.0.1:5400"
      }
    ]
  },
  "self_link_party": "receiver"
}

// 服务端配置文件
{
  "kcal_pir_sender_config": {
    "threads": 16,									// 多线程处理，按需修改
    "db_file": "/tmp/db.csv",						// 数据库文件位置
	"use_sm_alg": false								// 是否启用国密算法
  },
  "link_config": {									// 两个参与方的通信 ip 和 端口，按需修改
    "parties": [
      {
        "id": "sender",
        "host": "127.0.0.1:5300"
      },
      {
        "id": "receiver",
        "host": "127.0.0.1:5400"
      }
    ]
  },
  "self_link_party": "sender"
}
```

#### kcal 两个配置文件

- examples/pir/config/kcal_pir_receiver.json
- examples/pir/config/kcal_pir_sender.json

#### 蚂蚁对比配置文件

- examples/pir/config/apsi_sender_setup.json
- examples/pir/config/apsi_sender_online.json
- examples/pir/config/apsi_receiver.json

#### 测试

进入两个 cvm 分别执行以下命令

```bash
cd /home/admin/dev/psi
# 服务端
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/path/to/kcal/lib ./bin/main --config $(pwd)/examples/pir/config/kcal_pir_sender.json
# 客户端
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/path/to/kcal/lib ./bin/main --config $(pwd)/examples/pir/config/kcal_pir_receiver.json
```

运行完以上命令后，客户端`cvm`内会在配置文件中指明的`kcal_pir_receiver_config.output_file`路径中生成查询结果文件

#### 结果对比

将`/tmp/result.csv`的内容与一开始生成的交集文件`/tmp/ground_truth.csv`内容进行比对，结果保持一致
