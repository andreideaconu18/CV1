#!/usr/bin/env tclsh

# Count how many times a number appears in a list

proc count_occurrences {lst number} {
    set count 0
    foreach element $lst {
        if {$element == $number} {
            incr count
        }
    }
    return $count
}

# Example usage
set my_list {1 3 5 3 7 3 9 2 3 4}
set target 3

set result [count_occurrences $my_list $target]
puts "The number $target appears $result time(s) in the list."
