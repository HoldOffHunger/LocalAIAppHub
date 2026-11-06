<?php

	/*
		Puts a bundle of YallHearingThis shows on a host -- production, when
		Ben says so -- through that host's own modify_entry.php, so every rule
		modify.php has runs there as it did on int.  The worker never runs this;
		a person does, for shows they've looked at.

			php push_bundle.php /tmp/yht-bundle            dry: says what it would do
			php push_bundle.php /tmp/yht-bundle --apply     does it

		The bundle (prod_bundle.py) holds manifest.json, a record per entry in
		modify.php's field names, and the pictures.  Entry ids differ between
		hosts, so a show names its artists by code, and they're turned into
		this host's ids here.  Anything already present -- a section or artist
		by its code, a show by its YouTube link -- is left alone.
	*/

	$bundle = rtrim($argv[1] ?? '', '/');
	$apply = in_array('--apply', $argv, TRUE);
	$manifest = json_decode((string) @file_get_contents($bundle . '/manifest.json'), TRUE);

	if(!is_array($manifest)) {
		fwrite(STDERR, "No manifest.json in '$bundle'.\n");
		exit(1);
	}

	$modify = $manifest['modify_entry'] ?? '/usr/lib/ggcms/cli/scripts/internal/entries/modify_entry.php';
	$db = mysqli_connect();
	mysqli_select_db($db, $manifest['database']);

	function rows($db, $sql, $types = '', $values = []) {
		$statement = mysqli_prepare($db, $sql);
		if($types) {
			mysqli_stmt_bind_param($statement, $types, ...$values);
		}
		mysqli_stmt_execute($statement);
		return mysqli_fetch_all(mysqli_stmt_get_result($statement), MYSQLI_ASSOC);
	}

	function root_id($db) {
		return (int) (rows($db, 'SELECT Parentid FROM Assignment WHERE Childid = 0 LIMIT 1')[0]['Parentid'] ?? 0);
	}

	function child_id($db, $parent, $code) {
		$found = rows($db, 'SELECT e.id FROM Entry e JOIN Assignment a ON a.Childid = e.id WHERE a.Parentid = ? AND e.Code = ?', 'is', [$parent, $code]);
		return $found ? (int) $found[0]['id'] : 0;
	}

	function save($manifest, $modify, $bundle, $path, $name, $record, $apply) {
		foreach(($record['files'] ?? []) as $field => $files) {
			foreach($files as $i => $file) {
				$record['files'][$field][$i] = strlen($file) ? $bundle . '/images/' . basename($file) : '';
			}
		}
		$file = $bundle . '/posted-' . $name . '.json';
		file_put_contents($file, json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
		$command = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($modify) . ' ' . escapeshellarg($manifest['domain'])
			. ' --path=' . escapeshellarg($path) . ' --user=' . escapeshellarg($manifest['user'])
			. ' --fields-json=' . escapeshellarg($file) . ($apply ? ' --apply' : '') . ' 2>&1';
		$output = (string) shell_exec($command);
		preg_match('/^(Status|Refused)\s*:\s*(.*)$/m', $output, $status);
		preg_match_all('/^Error\s*:\s*(.*)$/m', $output, $errors);
		$said = trim(strip_tags($status[2] ?? (strpos($output, 'Dry run') !== FALSE ? 'dry run, fields read' : 'no status')));
		printf("  %-8s %-45s %s%s\n", $apply ? 'saved' : 'would', $path . ' ' . $name, substr($said, 0, 70),
			$errors[1] ? ' -- ' . implode('; ', $errors[1]) : '');
		return $apply ? (strpos($said, 'successful') !== FALSE) : TRUE;
	}

	$root = root_id($db);
	print(($apply ? 'Applying' : 'Dry run') . ' on ' . $manifest['domain'] . ', database ' . $manifest['database'] . ", root entry $root\n\n");

	$sections = [];
	foreach($manifest['sections'] as $code => $record) {
		$sections[$code] = child_id($db, $root, $code);
		if($sections[$code]) {
			print("  have     /$code/ (entry {$sections[$code]})\n");
			continue;
		}
		save($manifest, $modify, $bundle, '/', $code, $record, $apply);
		$sections[$code] = $apply ? child_id($db, $root, $code) : 0;
	}

	$artists = [];
	foreach($manifest['artists'] as $code => $record) {
		$artists[$code] = $sections['artists'] ? child_id($db, $sections['artists'], $code) : 0;
		if($artists[$code]) {
			print("  have     /artists/$code/ (entry {$artists[$code]})\n");
			continue;
		}
		if(!$sections['artists']) {
			print("  would    /artists/ $code (after the section is made)
");
			continue;
		}
		save($manifest, $modify, $bundle, '/artists/', $code, $record, $apply);
		$artists[$code] = ($apply && $sections['artists']) ? child_id($db, $sections['artists'], $code) : 0;
	}

	foreach($manifest['shows'] as $show) {
		$record = $show['record'];
		if(rows($db, 'SELECT Entryid FROM Link WHERE URL = ? LIMIT 1', 's', [$show['url']])) {
			print("  have     show {$show['url']}\n");
			continue;
		}
		$ids = [];
		foreach($show['artists'] as $code) {
			if($artists[$code] ?? 0) {
				$ids[] = (string) $artists[$code];
			} elseif($apply) {
				print("  missing  artist $code for {$show['url']}; the show goes up without that link\n");
			}
		}
		foreach(['ChosenEntryid', 'association_Type', 'association_SubType'] as $field) {
			unset($record['fields'][$field]);
		}
		if($ids) {
			$record['fields']['ChosenEntryid'] = $ids;
			$record['fields']['association_Type'] = array_fill(0, count($ids), 'Role');
			$record['fields']['association_SubType'] = array_fill(0, count($ids), 'Artist');
		}
		if(!$sections['shows']) {
			print("  would    /shows/ {$show['code']} (after the section is made)
");
			continue;
		}
		save($manifest, $modify, $bundle, '/shows/', $show['code'], $record, $apply);
	}

	print("\nDone.\n");

?>
