#include <stddef.h>
#include <stdint.h>

void matmul(int64_t* inMat, int64_t* outMat, size_t rows, size_t cols) {
  for (size_t i = 0; i < rows; i++) {
    for (size_t j = 0; j < rows; j++) {
      for (size_t k = 0; k < cols; k++) {
        outMat[i * rows + j] += inMat[i * cols + k] * inMat[j * cols + k];
      }
    }
  }
}