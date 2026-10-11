#include <stdio.h>

int main(void) {
    int n, x, broj = 0;
    scanf("%d", &n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &x);
        if (x % 2 == 1) {
            broj++;
        }
    }
    printf("%d\n", broj);
    return 0;
}
