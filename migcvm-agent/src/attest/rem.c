/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 */
#include <stdio.h>
#include <string.h>
#include "rem.h"

bool rem_init(rem_t* rem)
{
    if (!rem) return false;
    memset(rem->data, 0, REM_LENGTH_BYTES);
    return true;
}

bool rem_compare(const rem_t* rem1, const rem_t* rem2)
{
    if (!rem1 || !rem2) return false;
    return memcmp(rem1->data, rem2->data, REM_LENGTH_BYTES) == 0;
}

void rem_dump(const rem_t* rem)
{
    if (!rem) {
        return;
    }
    
    for (int i = 0; i < REM_LENGTH_BYTES; i++) {
        printf("%02x", rem->data[i]);
    }
    printf("\n");
}