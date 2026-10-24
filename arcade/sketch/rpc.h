#pragma once

#include <stdint.h>

#include "g3d_proto.h"

// g3d Bridge methods (api.md §2). Handlers run on the Bridge thread and only validate and copy;
// the render loop picks up the results through the functions below.
namespace rpc {

void begin();  // after Bridge.begin(): registers g3d_hello, g3d_scene_*, g3d_frame, g3d_release

bool latestFrame(g3d::Frame& out, uint32_t& ageMs);  // newest valid frame and how old it is
void markRendered(uint8_t seq);                      // echoed as seq_ack
bool applyScene();                                   // apply a committed upload; true -> re-bake
void setTimings(uint32_t renderUs, uint32_t pushUs); // reported back in Input
void setVideoActive(bool active);                    // RetroArch owns the display: reject frames
uint32_t framesReceived();                           // running count, for debug stats

}  // namespace rpc
