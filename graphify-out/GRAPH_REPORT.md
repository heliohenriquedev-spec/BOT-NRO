# Graph Report - BOT NRO  (2026-11-16)

## Corpus Check
- Large corpus: 328 files · ~4,641,151 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 4444 nodes · 14440 edges · 157 communities (134 shown, 23 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 2003 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 133
- Community 134
- Community 135
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154

## God Nodes (most connected - your core abstractions)
1. `SessionRelay` - 381 edges
2. `PacketHunt` - 243 edges
3. `CollisionMap` - 205 edges
4. `QuestRoutes` - 188 edges
5. `PortalGuard` - 139 edges
6. `CombatRotation` - 114 edges
7. `decode()` - 108 edges
8. `PacketPatrol` - 99 edges
9. `Entity` - 94 edges
10. `MapCombat` - 83 edges

## Surprising Connections (you probably didn't know these)
- `test_home_is_global_toggle_and_background_gate_does_not_require_focus()` --uses--> `GameControls`  [INFERRED]
  tests/test_packet_attack_control.py → nrobot/packet_controls.py
- `test_relay_records_monsters_and_captures_a_missing_sprite_when_the_mouse_rests_on_it()` --indirect_call--> `path()`  [INFERRED]
  tests/test_monsters_and_fast_skills.py → nrobot/auto_routes.py
- `test_hunt_window_offers_maps_reached_by_learned_portals()` --calls--> `HuntDialog`  [EXTRACTED]
  tests/test_auto_routes.py → nrobot/hunt_dialog.py
- `test_map_combat_does_not_inherit_the_ordinary_combat_tuning()` --calls--> `settings_for()`  [EXTRACTED]
  tests/test_map_combat.py → nrobot/map_combat.py
- `test_explicit_monster_type_does_not_wait_for_client_hover_requests()` --calls--> `is_confirmed_monster()`  [EXTRACTED]
  tests/test_resource_portability.py → nrobot/map_monsters.py

## Import Cycles
- None detected.

## Communities (157 total, 23 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.04
Nodes (49): QuestRoutes, build_routes(), validate(), test_progress_is_saved_and_the_queue_resumes_where_it_stopped(), test_quests_and_bg_travel_through_learned_portals_and_npcs(), test_combat_items_alone_are_equipped_before_the_hunt_even_without_mount(), test_missing_character_mount_is_skipped_and_route_continues_on_foot(), test_route_queues_mount_for_trips_gear_for_the_hunt_and_voltar_after_it() (+41 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (51): BgDamage, skill_names(), answer(), BgPanel, check_mode(), load(), messages(), npc_lines() (+43 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (48): PacketPatrol, test_patrol_starts_with_open_ground_and_leaves_the_walls_for_last(), comb(), test_keeping_off_walls_never_costs_a_long_detour(), test_maze_patrol_goes_to_the_nearest_pending_waypoint(), test_avoid_walls_keeps_the_route_interior_even_when_edge_route_is_shorter(), test_patrol_avoids_failed_ray_and_waits_if_all_exits_failed(), test_seeded_patrol_is_reproducible_and_prefers_unvisited_sector_over_heading() (+40 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (24): SessionRelay, test_relay_keeps_a_command_it_could_not_read(), test_loot_commands_are_queued_by_the_relay_and_bad_ones_refused(), test_relay_asks_showmobs_only_for_marked_monsters_and_reports_the_sweep(), test_failure_rules_can_be_switched_off(), test_attacker_check_keeps_automatic_and_named_targets(), test_discovery_is_passive_and_does_not_write_unvalidated_queries(), test_missing_collision_starts_stationary_without_disabling_setting() (+16 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (33): compact(), validate(), chebyshev(), load_defaults(), board(), board_rank(), kill_targets(), mission() (+25 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (11): is_database_hunt(), adopt_inner_portals(), apply(), inner_portals(), load(), for_character(), QuestRelay, test_repair_is_joined_at_the_furthest_reachable_map() (+3 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (42): PortalGuard, validate(), setup_queue(), test_inner_portal_that_never_warps_times_out_instead_of_waiting_forever(), test_sewer_trip_waits_for_each_inner_warp_and_continues_without_clearing_cache(), test_travel_leaves_the_arrival_portal_before_crossing_the_sewer(), test_access_validation_stops_at_destination_without_hunt(), test_checked_missions_are_all_taken_with_one_return_at_the_end() (+34 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (23): character_file(), learned_buff_links(), read(), read_character(), save(), save_character(), validate(), main() (+15 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (44): identity(), merge(), snapshot(), validate(), mob_info_species(), open_database(), save_mob_info(), server_drops() (+36 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (10): run(), reachable(), scenario(), scenario(), test_slow_cast_skill_waits_while_basic_attacks_can_land(), test_quest_hunt_apply_is_not_reapplied_by_map_behavior(), test_sleeping_target_kept_for_silence_and_doki_damage_gated(), test_planned_adjacent_attack_passes_relay_validation() (+2 more)

### Community 10 - "Community 10"
Cohesion: 0.04
Nodes (27): GroupHunt, Entity, HuntTargetChanged, test_rotation_interleaves_skill_with_pending_basic_attack_and_self_buff(), scenario(), relay(), test_follower_uses_leader_target_even_when_another_monster_is_closer(), test_no_independent_hunt_or_patrol_when_leader_is_missing() (+19 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (46): des_decrypt(), des_decrypt_block(), E(), FP(), IP(), RoundFunction(), SBOX(), TP() (+38 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (25): message_line(), MissionDetails, all_monsters(), clean(), mission_label(), mission_option(), npc_name(), plain() (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.06
Nodes (24): connection_pid(), GameControls, change_local_port(), connections(), install(), installed_port(), make_profile(), manifest() (+16 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (25): load_slots(), X1Box, choose(), chosen(), decide(), for_character(), import_file(), matches() (+17 more)

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (22): mark_key(), MobScan, test_empty_showmobs_round_retries_on_schedule_instead_of_disabling_the_map(), test_empty_scan_does_not_traverse_the_map(), test_scan_calculates_without_blocking_relay_and_discards_old_map_result(), scenario(), delayed(), scan_with() (+14 more)

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (11): calculate(), block_of(), PatrolTour, priority(), fork_map(), test_corridor_order_finishes_one_branch_before_another(), test_corridor_tip_must_actually_be_reached_before_being_marked(), test_cycle_reaches_safe_tips_and_respects_walls() (+3 more)

### Community 17 - "Community 17"
Cohesion: 0.10
Nodes (26): MapCombat, test_target_on_a_ground_skill_gets_only_throws_in_burst(), test_doki_is_attacked_anyway_when_the_silence_does_not_come(), kill_intent(), kill_intent(), test_burst_does_not_send_silence_during_confirmed_stun_delay(), test_control_can_preempt_unconfirmed_damage_after_global_delay(), test_jounin_put_to_sleep_and_silenced_is_attacked_normally() (+18 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (43): config(), test_old_damage_and_pending_attack_do_not_override_map_pick(), test_walled_control_target_does_not_block_nearby_ninkame(), kill_intent(), test_acquire_distant_target_and_keep_it_as_it_crosses_eight(), test_controlled_jounin_is_approached_to_silence_range_even_during_cooldown(), test_doki_passive_selected_without_targeting_but_silenced_before_damage(), test_first_offensive_does_not_wait_for_buff_renewal() (+35 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (26): data_ini_grfs(), _entries(), Entry, GrfError, GrfSet, decode_block(), decode_header(), decode_mixed() (+18 more)

### Community 20 - "Community 20"
Cohesion: 0.06
Nodes (5): PacketPanel, test_panel_sends_an_unconfirmed_command_again_then_gives_up(), test_group_panel_fields_save_without_starting_connection(), panel(), test_panel_global_delay_preserves_decimal_and_validates()

### Community 21 - "Community 21"
Cohesion: 0.13
Nodes (32): decode(), PresenceGuard, chat(), test_an_invisible_character_is_revealed_by_its_actions(), test_chat_emote_and_turning_carry_the_actor_but_never_the_text(), test_visible_or_just_departed_characters_are_not_invisible(), appearance_22c(), appearance_idle() (+24 more)

### Community 22 - "Community 22"
Cohesion: 0.10
Nodes (31): find(), catalog(), ensure_sprite(), export_base(), extract_all(), find_sprite(), identities(), is_monster_species() (+23 more)

### Community 23 - "Community 23"
Cohesion: 0.08
Nodes (32): backup(), apply(), backup(), can_publish(), check(), config(), distributed(), fetch() (+24 more)

### Community 24 - "Community 24"
Cohesion: 0.08
Nodes (39): argb(), catalog(), export_shared(), external_preview_definitions(), hides_native(), migrate_sides(), preview_definitions(), preview_visual() (+31 more)

### Community 25 - "Community 25"
Cohesion: 0.09
Nodes (20): database_hunt_route(), goal_reached(), item_count(), loot_command(), mark_showmobs(), monsters_by_map(), routes_by_map(), showmobs_marked() (+12 more)

### Community 26 - "Community 26"
Cohesion: 0.09
Nodes (21): data_stamp(), DropObserver, item_overview(), review(), rows(), chance(), DropDatabaseDialog, fill() (+13 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (25): RcxPanel, footprint(), load(), select_skill(), test_edit_is_on_disk_immediately_without_waiting_for_timer_or_shutdown(), test_editing_desperado_radius_automatically_enables_override_and_updates_rendering(), test_editing_shape_automatically_enables_override_and_survives_reopening(), test_further_edits_in_stale_panel_do_not_revert_merged_colors() (+17 more)

### Community 28 - "Community 28"
Cohesion: 0.14
Nodes (30): GroundCells, own_unit_skills(), rule(), test_cast_cancel_packet_removes_cast_area_immediately_but_not_real_units(), test_own_cast_preview_expires_and_does_not_create_confirmed_units(), test_unacknowledged_ground_request_never_paints_and_failure_clears_request(), entry(), ground_skill() (+22 more)

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (21): PlayerPanel, normalize_player_name(), detections(), add(), enabled(), load(), save(), set_enabled() (+13 more)

### Community 30 - "Community 30"
Cohesion: 0.10
Nodes (25): Body, chat_frame(), Errand, map_key(), test_any_broken_item_in_the_list_counts_even_not_worn(), test_break_packet_and_damaged_flag_are_read(), gear_body(), hit() (+17 more)

### Community 31 - "Community 31"
Cohesion: 0.09
Nodes (12): inspect(), map_key(), Cell, manifest(), Preview, RcxRenderer, Shared, test_closed_game_stops_the_heartbeat_and_the_panel_waits_for_the_new_one() (+4 more)

### Community 32 - "Community 32"
Cohesion: 0.10
Nodes (19): ClientFrameGuard, move(), client_lengths(), test_guild_info_query_following_master_query(), test_guild_master_query_does_not_block_injection(), test_injection_waits_for_complete_native_frames_across_tcp_chunks(), test_less_effect_fragmented_and_followed_by_native_actions(), test_manual_frame_telemetry_contains_metadata_only() (+11 more)

### Community 33 - "Community 33"
Cohesion: 0.09
Nodes (18): plan_cells(), CollisionMap, goal(), test_nearby_parallel_corridor_is_not_marked_through_a_wall(), test_reachable_components_and_strict_start_reject_invalid_position(), test_monsters_around_a_character_standing_in_a_skill_area_are_not_behind_a_wall(), test_plain_view_keeps_real_walls(), test_gat_layout_unknown_types_and_truncated_input() (+10 more)

### Community 34 - "Community 34"
Cohesion: 0.14
Nodes (36): validated_learning(), ack(), combat_with_summon(), effect(), p(), refused(), state(), test_a_summon_refused_again_and_again_waits_its_interval() (+28 more)

### Community 35 - "Community 35"
Cohesion: 0.11
Nodes (22): add_discarded(), as_entries(), event_talk(), gat(), harmful(), NpcTransports, purge(), read_discarded() (+14 more)

### Community 36 - "Community 36"
Cohesion: 0.06
Nodes (10): GmSigns, load_config(), staff_name(), reachable(), scenario(), scenario(), test_gm_signs_speed_guild_teleports_and_listed_visuals(), test_relay_sits_while_recovering_and_stands_to_summon() (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.10
Nodes (19): load(), save(), QuestMonsterIndex, RouteEditor, mission(), test_catalog_mode_saves_all_menu_options_without_accepting_any_mission(), test_catalog_selection_registers_only_checked_missions_and_keeps_all_options(), test_panel_command_runs_every_checked_mission() (+11 more)

### Community 38 - "Community 38"
Cohesion: 0.08
Nodes (17): names_from_catalog(), names_from_grfs(), prepare_item_names(), MapRepository, read_bundled_maps(), prepare(), validate_quest_maps(), visit() (+9 more)

### Community 39 - "Community 39"
Cohesion: 0.12
Nodes (22): EntityInventory, running_game(), confirmed_types(), is_confirmed_monster(), monster_assets(), is_known_player(), monster_choice_key(), record() (+14 more)

### Community 40 - "Community 40"
Cohesion: 0.11
Nodes (5): game_minimap_zoom(), ground_image(), MinimapOverlay, test_minimap_draws_and_resizes(), test_minimap_names_npcs_portals_and_showmobs_on_hover()

### Community 41 - "Community 41"
Cohesion: 0.11
Nodes (28): Board, data(), slots(), test_daily_mission_already_done_is_skipped_and_the_others_are_taken(), test_kakashi_mission_uses_the_vip_recording_without_its_own(), test_missions_of_one_board_skip_the_extra_reopening_but_are_still_checked(), test_refusal_after_accepting_already_done_is_skipped_too(), test_refused_mission_stops_with_the_board_answer() (+20 more)

### Community 42 - "Community 42"
Cohesion: 0.09
Nodes (16): copy_memory(), DllMain(), draw_cells(), entry_hook(), finite_matrix(), intercepted_state(), mix(), pick_at() (+8 more)

### Community 43 - "Community 43"
Cohesion: 0.09
Nodes (15): heuristic(), FrameBoundaryError, cells_at(), _Node, OpenGround, server_path(), add(), step_durations() (+7 more)

### Community 44 - "Community 44"
Cohesion: 0.10
Nodes (18): effective(), load(), map_key(), hunt_request(), MapBehaviorPanel, save(), validate(), validate() (+10 more)

### Community 45 - "Community 45"
Cohesion: 0.11
Nodes (13): test_a_confirmed_crossing_removes_a_false_inner_portal(), test_a_long_walk_into_the_portal_is_learned_from_the_walk_destination(), test_crossing_a_portal_records_where_it_leads_and_the_way_back(), test_inferred_way_back_never_overwrites_a_seen_crossing(), test_relay_order_new_map_already_current_when_the_change_arrives(), test_teleport_far_from_portals_records_nothing(), warp(), open_field() (+5 more)

### Community 46 - "Community 46"
Cohesion: 0.07
Nodes (16): VisionConfig, HandshakeFrames, rewrite_endpoints(), client_to_server(), server_to_client(), confirmed_monster(), accepted(), test_map_reconnect_keeps_character_data_but_replaces_map_entities() (+8 more)

### Community 47 - "Community 47"
Cohesion: 0.12
Nodes (21): LiveStream, message_length(), reassemble(), Segment, test_stream_fragmentation_duplicates_and_reordering(), test_stream_gap_conflict_and_unknown_stop(), test_unknown_custom_message_resyncs_without_inventing_events(), segment() (+13 more)

### Community 48 - "Community 48"
Cohesion: 0.09
Nodes (7): counter_lines(), GameOverlay, QuestCounter, game_client_rect(), test_own_shadow_is_drawn_on_the_view_centre_without_calibration(), test_in_game_counter_shows_done_and_missing_and_can_be_dragged(), test_overlay_draws_nothing_over_the_game_for_other_hidden_players()

### Community 49 - "Community 49"
Cohesion: 0.22
Nodes (30): settings_for(), learned(), mob(), rotation(), seal_ack(), state(), summon_learned(), test_a_buff_that_went_off_is_renewed_between_controls() (+22 more)

### Community 50 - "Community 50"
Cohesion: 0.12
Nodes (12): KuchiyoseDialog, SkillPanel, test_buff_link_survives_empty_profiles_and_rebuilt_catalog(), test_kuchiyose_only_editable_in_modal_save_cancel_and_persistence(), test_ui_locks_names_and_preserves_skill_range_across_refresh(), app(), catalog(), test_learned_buff_is_enabled_once_and_user_uncheck_survives_refresh() (+4 more)

### Community 51 - "Community 51"
Cohesion: 0.14
Nodes (22): save(), load(), save(), test_a_repair_that_did_not_fix_it_is_not_repeated_at_once(), test_broken_weapon_goes_to_the_repairer_and_back_to_hunt_with_it(), test_cycle_dismounts_before_voltar_to_the_repairer(), test_repair_on_hunting_map_is_not_skipped_on_arrival(), test_repairer_talk_is_recorded_once() (+14 more)

### Community 52 - "Community 52"
Cohesion: 0.19
Nodes (26): CombatRotation, skill_category(), test_rotation_uses_current_ammo_then_waits_for_equipment_confirmation_before_next_skill(), profile(), state(), test_buff_is_renewed_just_before_its_learned_end(), test_buffs_renew_only_after_effect_ends_and_unconfirmed_buff_is_blocked(), test_character_chakra_feet_buff_full_expiration_and_renewal_cycle() (+18 more)

### Community 53 - "Community 53"
Cohesion: 0.12
Nodes (19): PacketHunt, test_probe_learns_and_saves_only_unique_effect_across_separate_reads(), test_wall_cache_is_discarded_after_portal(), state(), test_diagonal_kite_reaches_five_and_waits_for_diagonal_travel_time(), test_kiting_does_not_reuse_rejected_cells_or_cross_them(), test_own_broadcast_walk_keeps_destination_path_and_acknowledges_hunt(), test_range_six_kites_to_five_without_passing_the_requested_spacing() (+11 more)

### Community 54 - "Community 54"
Cohesion: 0.18
Nodes (23): test_wall_budget_does_not_hide_later_clear_line_monster(), test_wall_exclusion_ends_as_soon_as_monster_is_on_our_side(), test_an_unanswered_basic_attack_does_not_hold_the_next_one_for_long(), state(), test_a_short_way_around_is_still_hunted(), test_cast_stopping_walk_at_origin_does_not_invent_an_obstacle(), test_current_target_found_across_a_wall_is_dropped_unless_it_attacks(), test_detour_around_blocked_cells_is_not_a_wall() (+15 more)

### Community 55 - "Community 55"
Cohesion: 0.09
Nodes (20): edges(), gat(), load_destinations(), path(), reachable(), merge_destinations(), stage_on_the_way(), stage_steps() (+12 more)

### Community 56 - "Community 56"
Cohesion: 0.10
Nodes (12): disarm(), ipv4_from_ethernet(), legacy_filter_captures(), PktmonSession, run(), main(), selected_tcp(), legacy_filter() (+4 more)

### Community 57 - "Community 57"
Cohesion: 0.09
Nodes (11): CharacterSprite, read_act(), read_file(), read_pair(), _scaled(), silhouette(), walk_state(), work() (+3 more)

### Community 58 - "Community 58"
Cohesion: 0.14
Nodes (15): Observer, ServerClock, test_moving_appearance_uses_collision_path_not_line_through_wall(), test_unresolved_path_keeps_received_endpoints_instead_of_inventing_a_cell(), test_map_identity_survives_position_init_and_clears_on_transfer(), test_skills_survive_a_map_change_and_a_new_list_still_replaces_them(), test_confirmed_walk_uses_ground_even_inside_a_guarded_portal(), test_sewer_entrance_predicts_the_confirmed_walk_through_the_portal() (+7 more)

### Community 59 - "Community 59"
Cohesion: 0.12
Nodes (23): done_today(), key(), load(), load_all(), mark(), replace(), save_slots(), today_keys() (+15 more)

### Community 60 - "Community 60"
Cohesion: 0.11
Nodes (17): messages(), pending_items(), read(), send(), split(), stamp(), webhook_url(), Response (+9 more)

### Community 61 - "Community 61"
Cohesion: 0.17
Nodes (10): QuestPanel, describe(), load(), save(), test_invalid_drop_cannot_duplicate_or_lose_a_quest(), test_multiple_routes_move_as_a_block_and_keep_selection_and_enabled(), setup_files(), test_completed_routes_start_unchecked_but_manual_selection_is_kept() (+2 more)

### Community 62 - "Community 62"
Cohesion: 0.15
Nodes (20): AmmoInventory, equip_ammo(), _hit(), inventory(), state(), test_equipment_refusal_timeout_and_consumption_never_mark_ammo_ready(), test_late_successful_equipment_ack_releases_timeout_backoff(), test_late_unequip_ack_for_old_stack_does_not_clear_new_ammo() (+12 more)

### Community 63 - "Community 63"
Cohesion: 0.12
Nodes (14): item_names(), base62(), item_identity(), MobInfoQueue, parse(), server_text(), route_done_today(), test_base62() (+6 more)

### Community 64 - "Community 64"
Cohesion: 0.12
Nodes (14): alignment(), distance_to(), weighed(), test_melee_with_skills_walks_up_instead_of_holding_kunai_range(), state(), test_patrol_chosen_past_a_walled_monster_remembers_it(), test_patrol_failure_changes_direction_instead_of_repeating(), test_old_sightings_cannot_redirect_cycle_and_goal_is_a_close_waypoint() (+6 more)

### Community 65 - "Community 65"
Cohesion: 0.18
Nodes (18): ContinuousTracker, messages(), position(), test_continuous_candidate_requires_recent_player_and_preserves_id(), test_delayed_events_pause_selection_without_losing_tcp_continuity(), test_etw_batch_age_does_not_immediately_expire_reorder_wait(), test_gap_pauses_selection_then_discards_world(), test_unknown_or_idle_discards_targets() (+10 more)

### Community 66 - "Community 66"
Cohesion: 0.08
Nodes (13): free(), test_port_taken_by_another_program_moves_the_bot_to_a_free_one(), scenario(), test_boxed_in_by_skill_areas_lets_routes_cross_them(), scenario(), test_historical_inventory_is_not_rewritten_for_every_fast_status_tick(), test_open_panel_reader_defers_telemetry_without_stopping_hunt(), test_shutdown_closes_live_bridge_before_waiting_for_listener() (+5 more)

### Community 67 - "Community 67"
Cohesion: 0.12
Nodes (17): configure_client_game(), main(), check_game(), check_runtime(), main(), test_installer_preflight_checks_actual_game_folder(), prepare_installer(), run() (+9 more)

### Community 68 - "Community 68"
Cohesion: 0.10
Nodes (6): take(), data_stamp(), MonsterModel, MonsterPanel, plain(), test_monster_tab_lists_the_game_monsters()

### Community 69 - "Community 69"
Cohesion: 0.14
Nodes (13): ManualSkillDiagnostic, attack(), body_action(), filler(), ground_skill(), skill(), uint(), test_sit_and_stand_are_the_action_request_without_a_target() (+5 more)

### Community 70 - "Community 70"
Cohesion: 0.15
Nodes (17): _relay(), test_click_on_character_with_armed_tool_captures_it(), test_clicking_a_monster_or_self_does_not_capture(), test_focusing_a_player_ignores_every_monster_and_summon(), test_hunt_attacks_captured_character_before_closer_monster(), test_players_checked_in_the_pvp_list_reach_the_automatic_battle(), test_priority_is_dropped_when_the_player_leaves_the_screen(), test_priority_setting_is_validated() (+9 more)

### Community 71 - "Community 71"
Cohesion: 0.11
Nodes (12): clean(), combat_choices(), is_mount(), mount_choices(), parse_descriptions(), parse_names(), slots(), summary() (+4 more)

### Community 72 - "Community 72"
Cohesion: 0.23
Nodes (5): SummonQueue, test_map_change_clears_live_state_but_keeps_learned_duration(), test_unknown_lifetime_does_not_probe_a_visible_confirmed_creature(), test_a_new_summon_learns_that_it_creates_a_creature(), test_a_summon_counts_only_when_its_creature_is_born_and_is_sent_again_otherwise()

### Community 73 - "Community 73"
Cohesion: 0.13
Nodes (5): FieldWheelGuard, PanelLayout, UpdatePanel, confirmed(), local_version()

### Community 74 - "Community 74"
Cohesion: 0.15
Nodes (18): relay(), resumable(), test_a_kill_taken_over_by_another_player_does_not_count(), test_a_monster_my_summon_killed_counts_for_the_quest(), test_arriving_next_to_a_portal_steps_straight_away_first(), test_each_counted_kill_says_who_made_it(), test_finished_quest_monsters_are_not_brought_back_by_their_names(), test_group_members_kills_count_too() (+10 more)

### Community 75 - "Community 75"
Cohesion: 0.19
Nodes (7): server_line(), ToxicGround, test_cornered_inside_clouds_walks_over_them_instead_of_standing_still(), inventory(), test_predict_only_explicit_salamandra_cast_and_cancel_without_removing_real_units(), test_received_units_overlap_removal_and_map_reset(), test_route_detours_toxic_cells_and_escape_handles_start_inside()

### Community 76 - "Community 76"
Cohesion: 0.16
Nodes (14): ask_console(), candidates(), is_game_dir(), normalize(), pick_in_window(), save(), saved(), _subfolders() (+6 more)

### Community 77 - "Community 77"
Cohesion: 0.18
Nodes (6): decode_instruction(), _Reader, tables(), is_table(), plain(), job_names()

### Community 78 - "Community 78"
Cohesion: 0.15
Nodes (16): read_map_caches(), _cells(), grid(), test_approach_leads_moving_target_without_firing_at_its_future_position(), test_corrupt_or_unrelated_cache_files_are_ignored(), test_empty_route_is_unavailable_without_crashing(), test_hercules_mcache_files_are_read(), test_hunt_routes_around_wall_and_replans_after_target_moves() (+8 more)

### Community 80 - "Community 80"
Cohesion: 0.18
Nodes (13): priority(), rotation_priority(), _profiles(), _state(), test_priority_cycle_lets_later_skills_go_when_the_first_is_ready_again_at_once(), test_priority_skips_skill_without_sp_and_throws_share_one_slot(), test_user_priority_picks_first_usable_skill_in_order(), profile() (+5 more)

### Community 81 - "Community 81"
Cohesion: 0.13
Nodes (5): ExtrasBox, SwitchDialog, test_panel_box_saves_the_options(), test_switch_button_only_saves_the_choice_for_this_character(), test_switch_lists_every_mount_and_the_combat_equipment_in_two_tabs()

### Community 83 - "Community 83"
Cohesion: 0.14
Nodes (3): is_player_id(), cells(), Sides

### Community 84 - "Community 84"
Cohesion: 0.17
Nodes (12): character_look(), load(), PlayerRegistry, idle_character(), lua50_chunk(), name_all(), test_compiled_lua_tables_are_read_without_running_them(), test_level_sex_look_party_and_guild_title_are_kept() (+4 more)

### Community 85 - "Community 85"
Cohesion: 0.21
Nodes (14): cross(), poisoned(), relay_with_target(), state(), test_a_confirmed_hit_or_no_other_monster_keeps_the_target(), test_alone_in_poison_the_character_gets_as_close_as_the_area_allows(), test_alone_on_a_skill_area_the_monster_is_not_given_up(), test_basic_attacks_go_on_during_the_coelho_seals() (+6 more)

### Community 86 - "Community 86"
Cohesion: 0.22
Nodes (11): build_reference(), check(), mask(), protected(), reference(), same_packet_table(), fake_client(), test_a_rebuilt_client_with_moved_calls_and_addresses_is_accepted() (+3 more)

### Community 87 - "Community 87"
Cohesion: 0.25
Nodes (10): ClientVision, status(), test_fragmented_account_and_messages_match_whole_stream(), test_live_factory_uses_account_actor_not_character_selection_id(), test_local_status_preserves_original_and_other_entities(), test_missing_character_id_never_injects(), test_toggle_restores_real_status_without_repeating_packets(), test_unknown_frame_is_reported_and_keeps_stream_intact() (+2 more)

### Community 89 - "Community 89"
Cohesion: 0.20
Nodes (13): counted_route(), relay_with(), test_a_moment_without_position_during_the_hunt_does_not_stop_the_queue(), scenario(), test_after_the_hunt_voltar_lands_elsewhere_then_mount_then_the_delivery_trip(), test_arriving_at_hunting_map_starts_combat_before_a_recorded_exit(), test_hunted_monsters_hitting_back_do_not_count_toward_the_ignore_limit(), test_ignoring_finished_and_other_monsters_but_not_the_marked_one() (+5 more)

### Community 90 - "Community 90"
Cohesion: 0.14
Nodes (9): distances(), goal_seeds(), plan(), submit(), test_cycle_walks_to_a_mark_already_on_the_minimap(), test_high_jump_crosses_a_wall_when_it_saves_the_walk(), test_jump_planning_waits_for_the_trip_steps(), test_validate_rejects_bad_stage() (+1 more)

### Community 91 - "Community 91"
Cohesion: 0.15
Nodes (5): clean_records(), excluded_spawn(), map_key(), MapTargets, test_targets_show_only_the_current_map_and_keep_other_maps_choices()

### Community 92 - "Community 92"
Cohesion: 0.13
Nodes (6): cells(), OwnSummons, test_a_creature_that_hits_me_is_not_my_summon(), test_a_summon_created_farther_away_is_mine_and_leaving_the_view_keeps_it(), test_only_what_appears_next_to_me_right_after_my_summon_is_mine(), test_the_players_own_feed_is_learned()

### Community 93 - "Community 93"
Cohesion: 0.15
Nodes (3): PriorityPanel, WrappingCheckBox, s()

### Community 94 - "Community 94"
Cohesion: 0.18
Nodes (15): put_menu(), test_all_selected_missions_are_confirmed_in_new_slots_before_return(), test_already_active_mission_is_not_accepted_twice(), test_board_counting_fewer_kills_takes_its_numbers_and_hunts_again(), test_deferred_delivery_is_saved_only_after_slot_confirmation(), test_delivery_ack_and_current_slot_removal_confirm_delivery(), test_delivery_is_proved_by_the_slot_not_by_a_message(), test_delivery_still_in_slot_stops_and_says_monsters_are_missing() (+7 more)

### Community 95 - "Community 95"
Cohesion: 0.16
Nodes (7): Header, windows_tick(), monster_sprite(), capture_under_cursor(), cursor(), grab(), write_png()

### Community 96 - "Community 96"
Cohesion: 0.18
Nodes (8): cleanup(), main(), start_guard(), watch(), active_session_file(), test_guard_preserves_mixed_filters(), test_guard_releases_own_capture_and_filter(), command()

### Community 97 - "Community 97"
Cohesion: 0.18
Nodes (3): describe(), QuestProgressLog, test_quest_progress_log_preserves_history_across_midnight_and_restart()

### Community 98 - "Community 98"
Cohesion: 0.23
Nodes (15): relay_for(), restart(), see(), test_a_gm_on_screen_by_name_really_stops_everything(), scenario(), test_gm_identification_can_be_switched_off(), scenario(), test_observation_stop_pauses_active_quest_and_cancels_automatic_returns() (+7 more)

### Community 99 - "Community 99"
Cohesion: 0.15
Nodes (9): Descriptor, EtwReader, event_callback(), Logfile, LogHeader, packet_payload(), Record, TraceEvent (+1 more)

### Community 100 - "Community 100"
Cohesion: 0.17
Nodes (9): analyze(), character_look_fields(), combat_notice(), main(), movement(), position(), read_pcapng(), write_report() (+1 more)

### Community 101 - "Community 101"
Cohesion: 0.14
Nodes (6): run(), search(), test_learning_an_inner_portal_invalidates_an_unreachable_cached_path(), test_exact_jump_points_are_not_skipped_by_shortcut(), test_a_recorded_detour_out_of_the_map_and_back_is_skipped_when_walkable(), test_long_route_search_runs_in_the_background()

### Community 102 - "Community 102"
Cohesion: 0.28
Nodes (13): state(), test_arrival_correction_cannot_be_delayed_by_an_older_walk_ack(), test_duplicate_ack_without_server_timing_does_not_restart_walk_wait(), test_failed_destination_is_not_retried_for_a_different_target_without_map(), test_in_range_combat_does_not_recompute_a_walk_route(), test_missing_acceptance_has_short_deadline_and_does_not_resend(), test_monster_motion_is_not_own_rejection_and_unrelated_route_is_not_ack(), test_own_correction_retains_target_and_replans_after_failed_step() (+5 more)

### Community 103 - "Community 103"
Cohesion: 0.31
Nodes (13): hunt(), metadata(), ready(), test_both_server_skill_damage_formats_confirm_matching_cast(), test_configured_interval_timeout_attempt_count_and_deferral_control_execution(), test_moving_target_destination_is_used_for_approach_and_range_is_bounded(), test_reached_moving_destination_with_old_start_position_does_not_wait_forever(), test_removal_does_not_confirm_skill_damage() (+5 more)

### Community 104 - "Community 104"
Cohesion: 0.19
Nodes (4): Publisher, Reader, test_direct_stream_updates_without_ui_refresh_and_stale_stream_clears(), test_stream_ignores_incomplete_frame()

### Community 105 - "Community 105"
Cohesion: 0.19
Nodes (6): configured_range(), profile(), state(), test_alternating_throws_reads_server_cooldown_even_without_local_timer(), test_alternating_throws_uses_ready_kunai_when_shuriken_is_out_of_range(), test_throws_take_their_turn_in_a_burst_and_the_ammo_is_swapped_in_that_turn()

### Community 106 - "Community 106"
Cohesion: 0.20
Nodes (9): ImmediateMonsterRemoval, test_double_attack_is_drawn_as_one_hit_with_the_same_damage(), ground_skill(), test_dropped_packets_never_reach_the_client_and_others_pass(), test_fire_pillar_draws_its_3x3_around_the_received_cell(), test_heartbeat_file_tells_the_relay_rcx_is_drawing(), test_overlapping_effects_are_both_drawn_on_the_shared_cells(), test_relay_hides_only_while_rcx_draws() (+1 more)

### Community 107 - "Community 107"
Cohesion: 0.28
Nodes (5): TargetRegistry, test_character_disguised_with_monster_sprite_is_never_a_monster_target(), test_choose_keeps_identity_until_removed(), test_out_of_order_map_change_and_expiry(), test_reject_non_targets_dead_stale_and_outside_range()

### Community 108 - "Community 108"
Cohesion: 0.17
Nodes (6): bring_game_to_front(), find_game_window(), executable(), visit(), game_in_front(), game_window()

### Community 109 - "Community 109"
Cohesion: 0.27
Nodes (8): closest_connection(), TravelCost, leg(), test_distinct_arrivals_on_same_map_are_compared_to_next_portal(), test_final_npc_approach_is_part_of_route_comparison(), test_nearby_two_hop_path_beats_distant_direct_portal(), test_real_walk_around_wall_is_used_instead_of_straight_distance(), test_transport_arrival_prices_the_walk_after_it()

### Community 111 - "Community 111"
Cohesion: 0.28
Nodes (10): profile(), snapshot(), test_invalid_distances_are_rejected(), test_invocation_needs_ground_type_but_no_enemy_and_respects_interval(), test_override_controls_planning_navigation_and_basic_attack_priority(), test_profile_settings_preserve_custom_distance(), test_relay_sends_self_or_ground_packet_and_validates_cells(), test_self_offensive_success_ack_is_execution_not_fake_damage() (+2 more)

### Community 112 - "Community 112"
Cohesion: 0.32
Nodes (11): choose_delivery(), menu(), open_board(), say(), select(), test_all_delivered_resume_ends_without_returning_to_hunt(), test_expired_mission_is_not_marked_delivered(), test_manual_delivery_requires_confirmation_and_survives_resume() (+3 more)

### Community 113 - "Community 113"
Cohesion: 0.20
Nodes (10): prepared(), test_attack_sends_one_packet_and_matches_server_source_and_target(), scenario(), test_focus_panic_and_expired_target_prevent_sending(), scenario(), test_home_is_global_toggle_and_background_gate_does_not_require_focus(), test_quiet_relay_does_not_permanently_invalidate_connection(), test_unrelated_damage_does_not_confirm_packet_test() (+2 more)

### Community 114 - "Community 114"
Cohesion: 0.24
Nodes (5): send_command(), load(), ShowmobsCyclePanel, save(), test_start_keeps_the_chosen_stage_after_saving()

### Community 115 - "Community 115"
Cohesion: 0.26
Nodes (7): command_line(), free(), is_bot_relay(), listening_pids(), run(), test_listening_process_is_found_on_a_portuguese_windows(), test_only_bot_relays_are_ended()

### Community 116 - "Community 116"
Cohesion: 0.24
Nodes (7): profile(), state(), test_bot_sits_while_a_player_is_near_and_stands_before_resuming(), test_burst_confirmation_releases_retry_wait_and_server_cooldown_still_wins(), test_burst_interleaves_skills_but_paces_retries_of_unanswered_requests(), test_server_cooldown_still_holds_a_skill_in_burst(), Writer

### Community 117 - "Community 117"
Cohesion: 0.29
Nodes (3): is_npc(), NpcMap, test_npcs_are_recorded_with_names_and_warps_or_monsters_are_not()

### Community 119 - "Community 119"
Cohesion: 0.30
Nodes (6): unexpected_teleport(), portals(), test_death_transfer_is_not_misclassified_as_recall(), test_map_change_far_from_portals_is_a_teleport(), test_relay_ignores_map_changes_it_expects(), test_relay_stops_everything_when_recalled_while_hunting()

### Community 120 - "Community 120"
Cohesion: 0.33
Nodes (11): allied(), bg_packet(), sides_relay(), test_bat_map_name_alone_marks_the_battleground(), test_battleground_team_decides_over_village(), test_battleground_team_packet_is_decoded(), test_map_without_pvp_every_player_is_allied_and_monsters_are_not(), test_old_files_default_sides_become_unchecked_and_user_choices_stay() (+3 more)

### Community 121 - "Community 121"
Cohesion: 0.25
Nodes (5): PlayerHp, test_battlefield_bar_layout_and_invalid_ratio(), test_legacy_hp_bar_keeps_scaled_values_separate_from_absolute_hp(), test_passive_evidence_tracks_players_outside_guild_without_inventing_hp(), test_relay_status_publishes_passive_hp_diagnostic()

### Community 123 - "Community 123"
Cohesion: 0.25
Nodes (6): relay_with_monster(), state(), test_manual_movement_keeps_skills_clearly_inside_their_range(), test_manual_movement_never_walks_and_takes_the_nearest_target(), test_sleeping_target_can_be_sent_an_attack(), test_sleeping_target_remains_in_combat_candidates()

### Community 124 - "Community 124"
Cohesion: 0.31
Nodes (6): require(), wall_distance(), init_worker(), main(), main_ground(), simulate()

### Community 125 - "Community 125"
Cohesion: 0.47
Nodes (8): private_packet(), public_packet(), test_private_message_decodes_sender_without_retaining_contents(), test_public_message_can_use_registered_name_and_removing_watch_stops_new_alerts(), test_public_or_private_message_triggers_for_watched_senders(), test_system_notices_emotes_and_whisper_delivery_ack_do_not_alert(), test_unwatched_messages_and_empty_watchlist_do_not_alert(), test_watched_id_matches_public_id_and_private_registered_name()

### Community 126 - "Community 126"
Cohesion: 0.40
Nodes (9): field(), kite_hunt(), test_cornered_against_a_wall_kites_sideways_to_open_ground(), test_dead_end_pocket_is_left_instead_of_backing_deeper(), test_open_ground_keeps_the_plain_retreat(), hunt_state(), test_basic_attacks_on_approach_for_melee_off_preserves_ranged_kiting(), test_running_away_goes_around_a_wall() (+1 more)

### Community 127 - "Community 127"
Cohesion: 0.31
Nodes (4): apply(), published(), test_no_published_patrol_keeps_settings(), test_published_patrol_is_exported_and_laid_over_every_hunt()

### Community 128 - "Community 128"
Cohesion: 0.25
Nodes (3): chat_command(), test_relay_sends_mi_and_saves_the_answer(), scenario()

### Community 129 - "Community 129"
Cohesion: 0.36
Nodes (7): state(), test_basic_attack_interleaves_only_with_the_target_in_reach(), test_blocked_diagonal_is_not_basic_attack_reach(), test_both_off_waits_at_skill_range_without_walking_or_retreating(), test_revalidation_keeps_target_and_does_not_defer_it(), test_toggle_switches_between_melee_approach_kite_and_holding_at_skill_range(), test_two_cells_must_approach_then_attack_without_losing_target()

### Community 130 - "Community 130"
Cohesion: 0.44
Nodes (7): _appear(), name_request(), _relay(), test_minimap_files_hold_ground_trail_and_patrol_plan(), test_names_the_client_asks_for_characters_just_entering_the_view_do_not_capture(), test_resting_the_game_mouse_on_a_character_captures_it_with_its_name(), test_showmobs_marks_reach_the_minimap_state_and_are_removed()

### Community 131 - "Community 131"
Cohesion: 0.25
Nodes (5): engine(), relay(), route(), test_reuses_directed_connections_from_unchecked_routes(), test_routes_persist_order_and_enabled_flags()

### Community 137 - "Community 137"
Cohesion: 0.33
Nodes (3): main(), dialogs_block_only_their_window(), test_dialogs_with_a_parent_do_not_block_the_overlays()

### Community 139 - "Community 139"
Cohesion: 0.48
Nodes (4): corridors(), routes(), test_goal_past_inner_portals_walks_onto_the_first_one_of_the_chain(), test_without_a_learned_link_the_goal_stays_unreachable()

### Community 140 - "Community 140"
Cohesion: 0.33
Nodes (3): observe_pktmon(), snapshot_summary(), test_pktmon_snapshot_keeps_filter_and_does_not_claim_current_target()

### Community 141 - "Community 141"
Cohesion: 0.33
Nodes (3): load(), linked_missions(), test_missions_of_other_quests_are_listed_with_their_names_but_not_the_own()

### Community 143 - "Community 143"
Cohesion: 0.53
Nodes (4): clearance(), first_leg(), ground(), safe_line()

### Community 144 - "Community 144"
Cohesion: 0.33
Nodes (3): test_relay_hunt_never_sends_without_focus_and_does_not_duplicate_pending(), scenario(), Writer

### Community 145 - "Community 145"
Cohesion: 0.60
Nodes (4): hunting(), kill(), test_a_sprite_other_than_this_pcs_list_is_learned_by_name_hunted_and_counted(), test_two_targets_sharing_a_sprite_are_counted_apart_by_name()

### Community 146 - "Community 146"
Cohesion: 0.60
Nodes (5): hit(), profile(), state(), test_each_skill_is_used_only_when_the_target_is_inside_its_own_range(), test_fast_mode_ignores_the_manual_interval_and_learns_a_shorter_wait()

## Knowledge Gaps
- **9 isolated node(s):** `srclen`, `srclen_aligned`, `declen`, `srcpos`, `next` (+4 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 1129 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SessionRelay` connect `Community 3` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 9`, `Community 10`, `Community 13`, `Community 14`, `Community 15`, `Community 17`, `Community 18`, `Community 19`, `Community 20`, `Community 21`, `Community 22`, `Community 25`, `Community 26`, `Community 27`, `Community 28`, `Community 29`, `Community 30`, `Community 32`, `Community 33`, `Community 34`, `Community 35`, `Community 36`, `Community 37`, `Community 39`, `Community 41`, `Community 44`, `Community 46`, `Community 49`, `Community 51`, `Community 52`, `Community 53`, `Community 54`, `Community 59`, `Community 62`, `Community 63`, `Community 65`, `Community 66`, `Community 69`, `Community 70`, `Community 74`, `Community 75`, `Community 78`, `Community 80`, `Community 83`, `Community 84`, `Community 85`, `Community 87`, `Community 89`, `Community 90`, `Community 92`, `Community 94`, `Community 95`, `Community 98`, `Community 102`, `Community 103`, `Community 104`, `Community 105`, `Community 106`, `Community 111`, `Community 113`, `Community 116`, `Community 117`, `Community 119`, `Community 121`, `Community 123`, `Community 125`, `Community 128`, `Community 129`, `Community 130`, `Community 131`, `Community 134`, `Community 138`, `Community 143`, `Community 144`, `Community 147`, `Community 150`?**
  _High betweenness centrality (0.209) - this node is a cross-community bridge._
- **Are the 44 inferred relationships involving `SessionRelay` (e.g. with `AmmoInventory` and `BgDamage`) actually correct?**
  _`SessionRelay` has 44 INFERRED edges - model-reasoned connections that need verification._
- **What connects `srclen`, `srclen_aligned`, `declen` to the rest of the system?**
  _9 weakly-connected nodes found - possible missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.04436945381827272 - nodes in this community are weakly interconnected._
- **Why does `CollisionMap` connect `Community 33` to `Community 0`, `Community 129`, `Community 2`, `Community 3`, `Community 4`, `Community 130`, `Community 6`, `Community 131`, `Community 9`, `Community 10`, `Community 139`, `Community 14`, `Community 15`, `Community 16`, `Community 18`, `Community 19`, `Community 25`, `Community 34`, `Community 38`, `Community 39`, `Community 40`, `Community 41`, `Community 43`, `Community 45`, `Community 49`, `Community 52`, `Community 53`, `Community 54`, `Community 58`, `Community 64`, `Community 66`, `Community 70`, `Community 74`, `Community 75`, `Community 78`, `Community 85`, `Community 90`, `Community 101`, `Community 102`, `Community 105`, `Community 109`, `Community 111`, `Community 119`, `Community 123`, `Community 126`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `PacketHunt` (e.g. with `PacketPatrol` and `test_monsters_around_a_character_standing_in_a_skill_area_are_not_behind_a_wall()`) actually correct?**
  _`PacketHunt` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.05692883895131086 - nodes in this community are weakly interconnected._