## 前置条件
需安装kcal包

## 编译
```
cd src
rm build && mkdir build
cmake -B build
cd build
make
```

## 如何运行示例
1. 在终端中切换到当前目录， 执行`bash hostrun0.sh`,
2. 另起一个终端，并切换到当前目录， 执行`bash hostrun1.sh`,
3. 等待5秒钟后， 会在第一个终端打印出结果。

## 算子
1. `./src/build/mpc_demo ./data/NodeId0.csv ./data/NodeId1.csv 1 7 127.0.0.1 127.0.0.1 10001 10002` 中的`7` 表示`/usr/local/include/data_guard_mpc.h` 中 `DG_AlgorithmsType` 第`7`个算子， 可以根据需要自行选择算子。
2. 当前算子使用的LT(小于)算子，因此当前的结果表示NodeId0.csv中的数据是否小于NodeId1.csv中的数据。

## 结果分析
1. `data` 目录包含测试数据，其中`NodeId0.csv`是节点0数据， `NodeId1.csv` 是节点1数据,
2. 在第一个终端输出结果：`kcal compute revealed result: 0 1 0 1`
3. 含义解释：表示NodeId0.csv 中与NodeId1.csv中的数据大小关系是：不小于、小于、不小于、小于。
