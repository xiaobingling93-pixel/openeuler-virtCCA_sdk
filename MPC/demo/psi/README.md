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
1. 在终端中切换到当前目录， 执行`bash server.sh`,
2. 另起一个终端，并切换到当前目录， 执行`bash client.sh`,
3. 等待5秒钟后， 会在当前目录生成结果文件。

## 结果分析
1. `data` 目录包含测试数据，其中`server.csv`是服务端数据， `client.csv` 是发送端数据,
2. 在当前目录输出结果文件： `output-*-server.csv`， `output-*-client.csv`,
3. 在输出结果文件中保存的是对应测试数据的下标。
