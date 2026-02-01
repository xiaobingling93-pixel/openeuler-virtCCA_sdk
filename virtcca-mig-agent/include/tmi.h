/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
 */

#ifndef TMI_H
#define TMI_H
#include <unistd.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <linux/types.h>

typedef struct {
    int fd;
} tmi_ctx;

/*
 * @brief   Init ctx.
 * @return  TMI context
 */
tmi_ctx *tmi_new_ctx(void);

/*
 * @brief   Free ctx.
 * @param   ctx [IN] TMI context
 */
void tmi_free_ctx(tmi_ctx *ctx);

/*
 * @param   ctx       [IN] TMI context
 * @param   cmd_id    [IN] tmi ioctl commond id
 * @param   flags     [IN] tmi ioctl commond flags
 * @param   data      [IN] tmi ioctl commond user data
 * @param   ret_val   [OUT] tmi ioctl commondreturn val
 * @return  error code
 */
int virtcca_tmi_ioctl(tmi_ctx *ctx, int cmd_id, int flags, void *data, uint64_t *ret_val);

struct virtcca_tmi_cmd {
	__u32 id;
	__u32 flags;
	__u64 data;
	__u64 ret_val;
};

#define TMI_MAGIC 'T'
#define VIRTCCA_TMI_IOCTL_ENTER _IOWR(TMI_MAGIC, 1, struct virtcca_tmi_cmd)
#define MAX_IP_LENGTH 16
#define MAX_NAME_LENGTH 64

/* virtcca tmi sub-ioctl() commands. */
enum virtcca_tmi_cmd_id {
	VIRTCCA_TMI_IOCTL_VERSION = 0,
	VIRTCCA_TMI_GET_NOTIFY,
	VIRTCCA_GET_MIGVM_MEM_CHECKSUM,
	VIRTCCA_GET_DSTVM_RD,

	VIRTCCA_TMI_IOCTL_CMD_MAX,
};

struct virtcca_mig_agent_notify_info {
	char		name[MAX_NAME_LENGTH];
	char		dst_ip[MAX_IP_LENGTH];
	uint64_t	rd;
	uint16_t	dst_port;
	uint16_t	cvm_vmid;
	uint16_t	is_src;	/*1: src, 0: dst*/
};
#endif
