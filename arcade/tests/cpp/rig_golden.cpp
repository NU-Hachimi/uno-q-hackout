// Prints every bone's rig-space origin for each rig, anim and golden phase as
// "<rig_id> <anim> <phase> <bone> <x> <y> <z>"; rig_golden.sh compares it with tests/golden/.
#include <stdio.h>

#include "rig.h"

int main() {
  static const uint8_t PHASES[] = {0, 64, 128, 192};
  rig::Xf bones[rig::MAX_BONES];
  for (int id = 0; id < gen::RIG_COUNT; ++id) {
    const gen::Rig& r = gen::RIGS[id];
    for (int a = 0; a < r.nAnims; ++a) {
      for (uint8_t phase : PHASES) {
        const int n = rig::pose(r, a, phase, bones);
        for (int b = 0; b < n; ++b)
          printf("%d %d %d %d %.5f %.5f %.5f\n", id, a, phase, b, bones[b].t[0], bones[b].t[1], bones[b].t[2]);
      }
    }
  }
  return 0;
}
