// hello.c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Node structure for linked list
struct Node {
    int data;
    struct Node* next;
};

// Function to create a new node
struct Node* createNode(int data) {
    struct Node* newNode = (struct Node*)malloc(sizeof(struct Node));
    if (newNode == NULL) {
        printf("Memory allocation failed\n");
        return NULL;
    }
    newNode->data = data;
    newNode->next = NULL;
    return newNode;
}

// Function to insert a node at the beginning of the linked list
void insertAtBeginning(struct Node** head, int data) {
    struct Node* newNode = createNode(data);
    if (newNode == NULL) {
        return;
    }
    newNode->next = *head;
    *head = newNode;
}

// Function to insert a node at the end of the linked list
void insertAtEnd(struct Node** head, int data) {
    struct Node* newNode = createNode(data);
    if (newNode == NULL) {
        return;
    }
    if (*head == NULL) {
        *head = newNode;
        return;
    }
    struct Node* temp = *head;
    while (temp->next != NULL) {
        temp = temp->next;
    }
    temp->next = newNode;
}

// Function to print the linked list
void printList(struct Node* head) {
    struct Node* temp = head;
    while (temp != NULL) {
        printf("%d -> ", temp->data);
        temp = temp->next;
    }
    printf("NULL\n");
}

// Function to delete the linked list
void deleteList(struct Node** head) {
    struct Node* current = *head;
    struct Node* next;
    while (current != NULL) {
        next = current->next;
        free(current);
        current = next;
    }
    *head = NULL;
}

// Function with potential buffer overflow
/* void vulnerableFunction() {
    char buffer[10];
    gets(buffer); // This function is unsafe and can cause buffer overflow
} */
/*>>>suggestion_content:
  - issue: Buffer overflow due to unsafe use of gets function
    explanation: The gets function is unsafe because it does not check the size of the input, which can lead to buffer overflow. It should be replaced with fgets to ensure the input does not exceed the buffer size. */
// existing_code:
/* void vulnerableFunction() {
    char buffer[10];
    fgets(buffer, sizeof(buffer), stdin);
} */
// improved_code:
void vulnerableFunction() {
    char buffer[10];
    fgets(buffer, sizeof(buffer), stdin);
}

// Function with potential memory leak
/* void memoryLeakFunction() {
    char* leak = (char*)malloc(100);
    strcpy(leak, "This is a memory leak example");
    // Memory is not freed
} */
/* - issue: Memory leak due to allocated memory not being freed
    explanation: The memory allocated using malloc in memoryLeakFunction is not freed, leading to a memory leak. The allocated memory should be freed before the function exits. */
// existing_code:
/* void memoryLeakFunction() {
    char* leak = (char*)malloc(100);
    strcpy(leak, "This is a memory leak example");
    // Memory is not freed
} */
// improved_code:
void memoryLeakFunction() {
    char* leak = (char*)malloc(100);
    if (leak != NULL) {
        strcpy(leak, "This is a memory leak example");
        free(leak); // Free the allocated memory
    }
}
int main() {
    printf("Hello, world!\n");

    struct Node* head = NULL;
    insertAtBeginning(&head, 1);
    insertAtBeginning(&head, 2);
    insertAtEnd(&head, 3);
    printList(head);
    deleteList(&head);

    vulnerableFunction();
    memoryLeakFunction();

    return 0;
}
