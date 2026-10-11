#include <stdio.h>

int main(void) {
    int n, x, zbroj = 0;
    scanf("%d", &n);
    for (int i = 1; i < n; i++) {
        scanf("%d", &x);
        zbroj += x;
    }
    printf("%d\n", zbroj);
    return 0;
}
