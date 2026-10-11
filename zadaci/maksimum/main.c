#include <stdio.h>

int main(void) {
    int n, x, maks = 0;
    scanf("%d", &n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &x);
        if (x > maks) {
            maks = x;
        }
    }
    printf("%d\n", maks);
    return 0;
}
