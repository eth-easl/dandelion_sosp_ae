#include <stdint.h>

#include <stdio.h>

#define QOI_IMPLEMENTATION
#include "qoi.h"

#define PNG_ONLY
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"


int32_t compress(const void* in_qoi,
        int32_t qoi_size,
        unsigned char** out_png){
    qoi_desc in_descriptor = {};
    void* pixels = qoi_decode(in_qoi, qoi_size, &in_descriptor, 0);
    if (pixels == NULL) {
        return -1;
    }
    int len;
    *out_png = stbi_write_png_to_mem(
        pixels,
        0,
        in_descriptor.width,
        in_descriptor.height,
        in_descriptor.channels,
        &len
    );
    free(pixels);
    return len;
}