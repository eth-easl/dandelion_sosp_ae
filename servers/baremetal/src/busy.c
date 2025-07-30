// System Headers
#include <stdint.h>
#include <stddef.h>
// Standard Libraries

#define ARRAY_ITEMS 16

typedef struct data_item {
  int8_t value[ARRAY_ITEMS];
} data_item;

void busy(uint64_t iterations, size_t max_index, data_item* data_items,
  int64_t* res_sum, int64_t* res_min, int64_t* res_max) {
  // the agreggated statistics we want to collect
  // sum, average, variance, min, max
  int64_t sum = 0;
  int64_t min = 256;
  int64_t max = -256;

  size_t struct_index = 0;
  size_t value_index = 0;
  for (size_t iteration = 0; iteration < iterations; iteration++) {
    for (size_t array_index = 0; array_index < ARRAY_ITEMS; array_index++) {
      int8_t value = data_items[struct_index].value[array_index];
      if (value > max)
        max = value;
      if (value < min)
        min = value;
      sum += value;
    }
    // using size_t which has no sign, guarantees that the index is not negative
    // when computing the remainder
    struct_index =
        (struct_index + data_items[struct_index].value[value_index]) %
        max_index;
    value_index = (value_index + 1) % ARRAY_ITEMS;
  }

  *res_sum = sum;
  *res_min = min;
  *res_max = max; 

  return;
}
