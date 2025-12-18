// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#pragma once

#include <vector>

#include "kcal/utils/io.h"

namespace kcal {

// Obtain a non-owning vector of shared pointers
const std::vector<io::KcalMpcShare *> BorrowPtrs(const std::vector<io::KcalMpcShare> &in)
{
    std::vector<io::KcalMpcShare *> out;
    out.reserve(in.size());
    for (const auto &elem : in) {
        // FIXME(cuijiming): we should not use const_cast here, but it's harmless since we return a const
        out.emplace_back(const_cast<io::KcalMpcShare *>(&elem));
    }
    return out;
}

} // namespace kcal
