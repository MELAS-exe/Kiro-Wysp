package dev.wysp.sample;

import java.util.ArrayList;
import java.util.List;

/** A book of the library, with the ratings readers gave it (1 to 5). */
public class Book {
    private final String title;
    private final String author;
    private final List<Integer> ratings = new ArrayList<>();

    public Book(String title, String author) {
        this.title = title;
        this.author = author;
    }

    public String getTitle() {
        return title;
    }

    public String getAuthor() {
        return author;
    }

    public void rate(int stars) {
        if (stars < 1 || stars > 5) {
            throw new IllegalArgumentException("A rating is between 1 and 5 stars");
        }
        ratings.add(stars);
    }

    public List<Integer> getRatings() {
        return ratings;
    }
}
