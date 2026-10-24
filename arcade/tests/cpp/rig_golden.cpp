// Prints sketch/rig.cpp poses in the layout of tests/golden/rig_<name>.json, for rig_golden.sh.
#include <stdio.h>

#include "rig.h"

int main() {
  static const int PHASES[] = {0, 64, 128, 192, 255};
  const float points[4][3] = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
  printf("{\"rigs\": [");
  bool firstRig = true;
  for (int id = 1; id < 256; ++id) {
    const gen::Rig* r = rig::find(uint8_t(id));
    if (!r) break;
    printf("%s{\"id\": %d, \"anims\": [", firstRig ? "" : ", ", id);
    firstRig = false;
    for (int a = 0; a < r->nAnims; ++a) {
      printf("%s[", a ? ", " : "");
      for (int p = 0; p < 5; ++p) {
        rig::Xform bones[rig::MAX_BONES];
        rig::pose(*r, uint8_t(a), uint8_t(PHASES[p]), bones);
        printf("%s[", p ? ", " : "");
        for (int m = 0; m < r->nBones + r->nSlots; ++m) {
          const rig::Xform x = m < r->nBones ? bones[m] : rig::slot(*r, bones, m - r->nBones);
          printf("%s[", m ? ", " : "");
          for (int k = 0; k < 4; ++k) {
            float out[3];
            rig::apply(x, points[k], out);
            printf("%s%.5f, %.5f, %.5f", k ? ", " : "", out[0], out[1], out[2]);
          }
          printf("]");
        }
        printf("]");
      }
      printf("]");
    }
    printf("]}");
  }
  printf("]}\n");
  return 0;
}
