| M01 | 3% cap `>` -> `>=` (<= vs <) | SURVIVED | **killed** | test_cap_3pct_exact_boundary_enters_and_tolerance_edge_enters_just_above_skips |
| M02 | 3% cap 0.03 -> 0.031 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_no_hardcoded_price_constants_in_sizing_path, test_property_sweep_price_atr_wallet_all_coins |
| M03 | 3% cap 0.03 -> 0.029 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_no_hardcoded_price_constants_in_sizing_path, test_property_sweep_price_atr_wallet_all_coins |
| M04 | 5% total cap `>` -> `>=` (sizing) | SURVIVED | **killed** | test_open_risk_cap_exact_boundaries_5pct_and_2_5pct |
| M05 | 5% total cap 0.05 -> 0.051 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M06 | 5% total cap 0.05 -> 0.049 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M07 | 2.5% q0 cap 0.025 -> 0.026 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M08 | 2.5% q0 cap 0.025 -> 0.024 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct |
| M09 | open-risk `>` -> `>=` (engine 2nd pass, 2.5%/5%) | SURVIVED | **killed** | test_engine_second_pass_open_risk_guard_boundary |
| M10 | engine 2nd-pass cap tolerance: cap + 1e-12 -> cap + 1e-3 (cap loosened) | SURVIVED | **killed** | test_engine_second_pass_open_risk_guard_boundary |
| M11 | sizing cap tolerance 1e-12 -> 1e-3 (loosened) | killed | **killed** | test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M12 | margin 90% `>` -> `>=` (<= vs <) | killed | **killed** | test_boundary_margin_plus_minus_one_percent |
| M13 | margin 90% -> 91% | killed | **killed** | test_boundary_margin_plus_minus_one_percent, test_no_hardcoded_price_constants_in_sizing_path |
| M14 | margin 90% -> 89% | killed | **killed** | test_boundary_margin_plus_minus_one_percent, test_no_hardcoded_price_constants_in_sizing_path |
| M15 | price buffer 2% -> 3% (param, both sites) | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick, test_property_sweep_price_atr_wallet_all_coins |
| M16 | price buffer 2% -> 1% (param, both sites) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_boundary_min_notional_plus_minus_one_tick |
| M17 | precheck worst-price buffer only: 0.98 -> 0.97 | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick |
| M18 | precheck worst-price buffer only: 0.98 -> 0.99 | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick |
| M19 | size_entry worst-price buffer only: 0.98 -> 0.97 | killed | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path, test_property_sweep_price_atr_wallet_all_coins |
| M20 | size_entry worst-price buffer only: 0.98 -> 0.99 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_filter_values_drive_the_quantity, test_no_alias_label_strings_in_emitted_skip_reasons, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip |
| M21 | minNotional precheck `<` -> `<=` (qty*worst == minNotional rejected) | SURVIVED | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path |
| M22 | minNotional precheck `<` -> `<` +1 tick (needs one step more) | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick, test_boundary_min_qty_plus_minus_one_step |
| M23 | q0 path minNotional `>=` -> `>` (q0*worst == minNotional goes to qty_floor) | SURVIVED | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path |
| M24 | q_min ceil_to -> floor_to (-1 tick below minNotional) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_filter_values_drive_the_quantity, test_no_alias_label_strings_in_emitted_skip_reasons, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip, test_sweep_price_scale_changes_notional_not_rules |
| M25 | q_min +1 tick (one step more than needed) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_min_qty_entry_is_the_smallest_allowed_quantity, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip |