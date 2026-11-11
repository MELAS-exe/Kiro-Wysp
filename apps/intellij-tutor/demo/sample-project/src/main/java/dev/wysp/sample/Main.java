package dev.wysp.sample;

public class Main {
    public static void main(String[] args) {
        Library library = new Library();
        library.add("The Hobbit", "J. R. R. Tolkien").rate(5);
        library.add("Dune", "Frank Herbert").rate(4);
        Book sapiens = library.add("Sapiens", "Yuval Noah Harari");
        sapiens.rate(3);
        sapiens.rate(5);

        System.out.println(library.size() + " books");
        for (Book book : library.ranking()) {
            System.out.printf("%-12s %.1f stars%n", book.getTitle(), library.calc(book));
        }
    }
}
