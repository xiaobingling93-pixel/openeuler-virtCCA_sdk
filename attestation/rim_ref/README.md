# 1. 编译构建
## 1.1 打开和关闭DEBUG模式
`vim ./CMakeLists.txt`
搜索`LOG_PRINT`关键字
- `LOG_PRINT=1` 表示打开DEBUG模式，使用工具生成极限值时会打印详细过程状态
- `LOG_PRINT=0` 表示不打开DEBUG模式（默认）

## 1.2 编译
```shell
# install go modules
cd inc/qemu_generator
go mod tidy

# compile
mkdir build && cd build
cmake ..
make

# deploy
cp ./gen_rim_ref /usr/local/bin
```
编译生成的二进制产物gen_rim_ref安装到/usr/local/bin目录下

# 2. 使用
`gen_rim_ref -h` 可查看帮助信息
使用基线工具生成基线值可产生如下文件，可用于调测等用途。
- 模拟的qemu启动命令：./build/qemu_params.conf
- dump生成的dtb文件：./build/dump.dtb
- 执行dumpdtb的日志：./build/dumpdtb.log

# 3. 注意事项
对于`kata-deploy`自动化部署场景，kata-qemu-virtcca容器运行时配置文件`/opt/kata/share/defaults/kata-containers/configuration-qemu-virtcca.toml`中指定的kernel路径默认是压缩路径，
即：`/opt/kata/share/kata-containers/vmlinuz-confidential.container`，需修改成对应非压缩kernel镜像路径。
即：`/opt/kata/share/kata-containers/vmlinux-confidential.container`。