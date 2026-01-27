# ==============================================================================
# IMPROVED EAR CENTER DETECTION - SUPPORTS VARIABLE NUMBER OF EARS
# ==============================================================================

# Original helper procs (unchanged)
proc makeCircleModelFrom3Points {pt1 pt2 pt3} {
    lassign $pt1 x1 y1
    lassign $pt2 x2 y2
    lassign $pt3 x3 y3

    set a11 [expr {$x2 - $x1}]
    set a12 [expr {$y2 - $y1}]
    set a21 [expr {$x3 - $x2}]
    set a22 [expr {$y3 - $y2}]

    set det [expr {$a11 * $a22 - $a12 * $a21}]

    if {abs($det) < 0.0001} {return "degenerate"}

    set inv_det [expr {1.0 / $det}]
    set b1 [expr {$x2*$x2 - $x1*$x1 + $y2*$y2 - $y1*$y1}]
    set b2 [expr {$x3*$x3 - $x2*$x2 + $y3*$y3 - $y2*$y2}]

    set cx [expr {($a22 * $b1 - $a12 * $b2) * $inv_det * 0.5}]
    set cy [expr {($a11 * $b2 - $a21 * $b1) * $inv_det * 0.5}]

    set dx [expr {$cx - $x1}]
    set dy [expr {$cy - $y1}]
    set r [expr {sqrt($dx*$dx + $dy*$dy)}]

    return [list $cx $cy $r]
}

proc evalCircleModelFast {cx cy r points} {
    set total_error 0.0

    foreach pt $points {
        lassign $pt x y
        set dx [expr {$x - $cx}]
        set dy [expr {$y - $cy}]
        set dist [expr {sqrt($dx*$dx + $dy*$dy)}]
        set total_error [expr {$total_error + abs($dist - $r)}]
    }

    return $total_error
}

proc ransacCircleFitFastWithRadius {points iterations} {
    set n [llength $points]

    if {$n < 3} {return "Not enough points"}

    set best_model {}
    set best_error 1e10

    set good_enough_error [expr {$n * 2.0}]

    for {set iter 0} {$iter < $iterations} {incr iter} {
        set idx1 [expr {int(rand() * $n)}]
        set idx2 [expr {int(rand() * $n)}]
        while {$idx2 == $idx1} {
            set idx2 [expr {int(rand() * $n)}]
        }
        set idx3 [expr {int(rand() * $n)}]
        while {$idx3 == $idx1 || $idx3 == $idx2} {
            set idx3 [expr {int(rand() * $n)}]
        }

        set model [makeCircleModelFrom3Points \
            [lindex $points $idx1] \
            [lindex $points $idx2] \
            [lindex $points $idx3]]

        if {$model == "degenerate"} {continue}

        lassign $model cx cy r
        set error [evalCircleModelFast $cx $cy $r $points]

        if {$error < $best_error} {
            set best_error $error
            set best_model $model

            if {$error < $good_enough_error} {
                break
            }
        }
    }

    if {[llength $best_model] == 0} {return "No valid model found"}

    return $best_model
}

proc fitCircleToCluster {points} {
    set n [llength $points]

    if {$n < 3} {
        puts "DEBUG: Cluster too small: $n points"
        return {}
    }

    set best_model {}
    set best_error 1e10

    set iterations [expr {$n < 6 ? 50 : 30}]

    for {set iter 0} {$iter < $iterations} {incr iter} {
        set idx1 [expr {int(rand() * $n)}]
        set idx2 [expr {int(rand() * $n)}]
        while {$idx2 == $idx1} {
            set idx2 [expr {int(rand() * $n)}]
        }
        set idx3 [expr {int(rand() * $n)}]
        while {$idx3 == $idx1 || $idx3 == $idx2} {
            set idx3 [expr {int(rand() * $n)}]
        }

        set model [makeCircleModelFrom3Points \
            [lindex $points $idx1] \
            [lindex $points $idx2] \
            [lindex $points $idx3]]

        if {$model == "degenerate"} {continue}

        lassign $model cx cy r

        if {$r < 6.0 || $r > 25.0} {continue}

        set error [evalCircleModelFast $cx $cy $r $points]

        if {$error < $best_error} {
            set best_error $error
            set best_model $model
        }
    }

    return $best_model
}

# ==============================================================================
# NEW: Estimate number of clusters using spatial separation
# ==============================================================================
proc estimateNumEars {points main_cx main_cy} {
    # Calculate distance from each point to main center
    set distances {}
    foreach pt $points {
        lassign $pt x y
        set dx [expr {$x - $main_cx}]
        set dy [expr {$y - $main_cy}]
        set dist [expr {sqrt($dx*$dx + $dy*$dy)}]
        lappend distances $dist
    }

    # Sort by distance
    set sorted_dists [lsort -real $distances]
    set n [llength $sorted_dists]

    # Look for gaps in distance distribution
    # Large gaps indicate separate clusters
    set gaps {}
    for {set i 1} {$i < $n} {incr i} {
        set prev [lindex $sorted_dists [expr {$i - 1}]]
        set curr [lindex $sorted_dists $i]
        set gap [expr {$curr - $prev}]
        lappend gaps $gap
    }

    # Count significant gaps (> median gap * 3)
    set sorted_gaps [lsort -real $gaps]
    set median_idx [expr {[llength $sorted_gaps] / 2}]
    set median_gap [lindex $sorted_gaps $median_idx]

    set num_clusters 0
    foreach gap $sorted_gaps {
        if {$gap > $median_gap * 3.0} {
            incr num_clusters
        }
    }

    # Add spatial clustering check: count distinct angular regions
    set angle_bins [dict create]
    foreach pt $points {
        lassign $pt x y
        set dx [expr {$x - $main_cx}]
        set dy [expr {$y - $main_cy}]
        set angle [expr {atan2($dy, $dx)}]

        # Bin angles into 12 sectors (30 degrees each)
        set bin [expr {int(($angle + 3.14159265359) / (2.0 * 3.14159265359 / 12.0))}]

        if {![dict exists $angle_bins $bin]} {
            dict set angle_bins $bin 0
        }
        dict incr angle_bins $bin
    }

    # Count bins with significant points (> 5% of total)
    set threshold [expr {[llength $points] * 0.05}]
    set active_bins 0
    dict for {bin count} $angle_bins {
        if {$count > $threshold} {
            incr active_bins
        }
    }

    # Estimate clusters from active bins (typically 2-4 bins per ear)
    set estimated_from_angles [expr {max(2, $active_bins / 2)}]

    # Use the maximum of both methods, capped at reasonable range
    set estimated [expr {max($num_clusters, $estimated_from_angles)}]
    set estimated [expr {max(2, min(6, $estimated))}]

    puts "DEBUG estimateNumEars: gaps=$num_clusters, angular=$estimated_from_angles, final=$estimated"
    return $estimated
}

# ==============================================================================
# NEW: K-means clustering with variable K
# ==============================================================================
proc clusterPointsKMeans {points k {max_iters 10}} {
    set n [llength $points]

    if {$n < $k * 3} {
        puts "DEBUG: Too few points ($n) for $k clusters"
        return {}
    }

    # Initialize centers by spreading them across the point cloud
    # Sort by X coordinate and pick evenly spaced points
    set sorted_points [lsort -real -index 0 $points]
    set centers {}
    for {set i 0} {$i < $k} {incr i} {
        set idx [expr {int($i * $n / double($k))}]
        if {$idx >= $n} {set idx [expr {$n - 1}]}
        lappend centers [lindex $sorted_points $idx]
    }

    puts "DEBUG: K-means with k=$k, initial centers: $centers"

    # K-means iterations
    for {set iter 0} {$iter < $max_iters} {incr iter} {
        # Assign each point to nearest center
        set clusters {}
        for {set i 0} {$i < $k} {incr i} {
            lappend clusters {}
        }

        foreach pt $points {
            lassign $pt x y

            # Find nearest center
            set min_dist 1e10
            set nearest_idx 0

            for {set i 0} {$i < $k} {incr i} {
                lassign [lindex $centers $i] cx cy
                set dx [expr {$x - $cx}]
                set dy [expr {$y - $cy}]
                set dist [expr {sqrt($dx*$dx + $dy*$dy)}]

                if {$dist < $min_dist} {
                    set min_dist $dist
                    set nearest_idx $i
                }
            }

            # Add point to nearest cluster
            lset clusters $nearest_idx [lappend [lindex $clusters $nearest_idx] [list $x $y]]
        }

        # Update centers
        set new_centers {}
        for {set i 0} {$i < $k} {incr i} {
            set cluster [lindex $clusters $i]

            if {[llength $cluster] == 0} {
                # Empty cluster, keep old center
                lappend new_centers [lindex $centers $i]
            } else {
                # Calculate mean
                set sum_x 0.0
                set sum_y 0.0
                foreach pt $cluster {
                    lassign $pt x y
                    set sum_x [expr {$sum_x + $x}]
                    set sum_y [expr {$sum_y + $y}]
                }
                set mean_x [expr {$sum_x / [llength $cluster]}]
                set mean_y [expr {$sum_y / [llength $cluster]}]
                lappend new_centers [list $mean_x $mean_y]
            }
        }

        set centers $new_centers
    }

    # Print cluster sizes
    for {set i 0} {$i < $k} {incr i} {
        puts "DEBUG: Cluster $i: [llength [lindex $clusters $i]] points"
    }

    return $clusters
}

# ==============================================================================
# IMPROVED: getEarCentersOnly with automatic ear count detection
# ==============================================================================
proc getEarCentersOnly {points} {
    puts "DEBUG: Starting with [llength $points] points"

    # Find main circle using RANSAC
    set result [ransacCircleFitFastWithRadius $points 50]

    if {![string is double [lindex $result 0]]} {
        puts "DEBUG: Failed to find main circle"
        return {}
    }

    if {[llength $result] != 3} {
        puts "DEBUG: Invalid result from RANSAC: $result"
        return {}
    }

    lassign $result cx cy r
    puts "DEBUG: Main circle: center=($cx, $cy), radius=$r"

    # Remove main circle points
    set tolerance 6.0
    set remaining_points {}

    foreach pt $points {
        lassign $pt x y
        set dx [expr {$x - $cx}]
        set dy [expr {$y - $cy}]
        set dist [expr {sqrt($dx*$dx + $dy*$dy)}]

        if {abs($dist - $r) > $tolerance} {
            lappend remaining_points [list $x $y]
        }
    }

    puts "DEBUG: Remaining points after removing main circle: [llength $remaining_points]"

    if {[llength $remaining_points] < 6} {
        puts "DEBUG: Not enough remaining points for ears"
        return {}
    }

    # Estimate number of ears
    set num_ears [estimateNumEars $remaining_points $cx $cy]
    puts "DEBUG: Estimated number of ears: $num_ears"

    # Cluster points using K-means
    set clusters [clusterPointsKMeans $remaining_points $num_ears]

    if {[llength $clusters] == 0} {
        puts "DEBUG: Clustering failed"
        return {}
    }

    # Fit circle to each cluster
    set ear_centers {}

    set cluster_num 0
    foreach cluster $clusters {
        incr cluster_num

        if {[llength $cluster] < 3} {
            puts "DEBUG: Cluster $cluster_num too small: [llength $cluster] points"
            continue
        }

        set ear_model [fitCircleToCluster $cluster]

        if {[llength $ear_model] == 3} {
            lassign $ear_model ear_cx ear_cy ear_r
            puts "DEBUG: Ear $cluster_num: center=($ear_cx, $ear_cy), radius=$ear_r"
            lappend ear_centers [list $ear_cx $ear_cy]
        }
    }

    puts "DEBUG: Found [llength $ear_centers] ear centers"
    return $ear_centers
}

# ==============================================================================
# KEPT FOR BACKWARD COMPATIBILITY: Original 2-cluster version
# ==============================================================================
proc clusterPoints {points {max_clusters 2}} {
    set n [llength $points]

    if {$n < 6} {
        puts "DEBUG: Too few points to cluster: $n"
        return {}
    }

    set sorted_x [lsort -real -index 0 $points]
    set cluster1_center [lindex $sorted_x 0]
    set cluster2_center [lindex $sorted_x end]

    puts "DEBUG: Initial cluster centers: $cluster1_center, $cluster2_center"

    for {set iter 0} {$iter < 5} {incr iter} {
        set cluster1_points {}
        set cluster2_points {}

        lassign $cluster1_center c1x c1y
        lassign $cluster2_center c2x c2y

        foreach pt $points {
            lassign $pt x y

            set dist1 [expr {sqrt(($x - $c1x)**2 + ($y - $c1y)**2)}]
            set dist2 [expr {sqrt(($x - $c2x)**2 + ($y - $c2y)**2)}]

            if {$dist1 < $dist2} {
                lappend cluster1_points [list $x $y]
            } else {
                lappend cluster2_points [list $x $y]
            }
        }

        if {[llength $cluster1_points] > 0} {
            set sum_x 0.0
            set sum_y 0.0
            foreach pt $cluster1_points {
                lassign $pt x y
                set sum_x [expr {$sum_x + $x}]
                set sum_y [expr {$sum_y + $y}]
            }
            set cluster1_center [list [expr {$sum_x / [llength $cluster1_points]}] [expr {$sum_y / [llength $cluster1_points]}]]
        }

        if {[llength $cluster2_points] > 0} {
            set sum_x 0.0
            set sum_y 0.0
            foreach pt $cluster2_points {
                lassign $pt x y
                set sum_x [expr {$sum_x + $x}]
                set sum_y [expr {$sum_y + $y}]
            }
            set cluster2_center [list [expr {$sum_x / [llength $cluster2_points]}] [expr {$sum_y / [llength $cluster2_points]}]]
        }
    }

    puts "DEBUG: Cluster 1: [llength $cluster1_points] points"
    puts "DEBUG: Cluster 2: [llength $cluster2_points] points"

    return [list $cluster1_points $cluster2_points]
}

# ==============================================================================
# USAGE EXAMPLE
# ==============================================================================
# Source this file and call getEarCentersOnly with your points
# The new version will automatically detect whether you have 2, 3, 4, or more ears
#
# Example:
# set points {{10 20} {15 25} {30 40} ...}
# set ear_centers [getEarCentersOnly $points]
# foreach center $ear_centers {
#     lassign $center cx cy
#     puts "Found ear at: ($cx, $cy)"
# }
