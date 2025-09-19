#ifndef VERIFY_H
#define VERIFY_H

#include <stdbool.h>
#include "rem.h"
#include "event_log.h"
#include "firmware_state.h"

/* Internal function declarations */
bool read_token_rem(rem_t rems[REM_COUNT]);
void verify_single_rem(int rem_index, const rem_t* rem1, const rem_t* rem2);

/**
 * @brief Verify firmware state hash values
 *
 * @param json_file JSON file path
 * @param state Firmware state
 * @return true Verification successful
 * @return false Verification failed
 */
bool verify_firmware_state(const char* json_file, const firmware_log_state_t* state);


#endif /* VERIFY_H */