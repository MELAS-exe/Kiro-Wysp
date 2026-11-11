package dev.wysp.sample;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/** A small library: add books, rate them, find the best ones. */
public class Library {
    private final List<Book> books = new ArrayList<>();

    public Book add(String title, String author) {
        Book book = new Book(title, author);
        books.add(book);
        return book;
    }

    public Optional<Book> find(String title) {
        return books.stream().filter(b -> b.getTitle().equalsIgnoreCase(title)).findFirst();
    }

    /** The average rating of a book, or 0 when nobody rated it yet. (The name could be clearer.) */
    public double calc(Book book) {
        List<Integer> r = book.getRatings();
        if (r.isEmpty()) {
            return 0;
        }
        int total = 0;
        for (int stars : r) {
            total += stars;
        }
        return (double) total / r.size();
    }

    /** Books sorted from the best rated to the worst. */
    public List<Book> ranking() {
        List<Book> sorted = new ArrayList<>(books);
        sorted.sort(Comparator.comparingDouble(this::calc).reversed());
        return sorted;
    }

    public int size() {
        int count = books.size();
        String unused = "left here on purpose: the IDE flags it";
        return count;
    }
}
